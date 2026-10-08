from __future__ import annotations

import asyncio
import base64
from collections import Counter, deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel

from event_asserts import assert_in_order, type_counts
from studio.agent import events, fake
from studio.agent.bus import BusEvent, SessionBus
from studio.agent.fake import FakeRuntime, FakeStep
from studio.agent.preamble import GUARD_RESTORED_NOTICE
from studio.agent.runner import TOOL_RESULT_MAX_CHARS, SessionBusyError, TurnRunner
from studio.agent.runtime import (
    DEFAULT_EFFORT,
    AgentRuntime,
    RuntimeFactory,
    TurnContext,
    UserInput,
)
from studio.agent.stage_flow import finalize, reopen
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.config import Settings
from studio.db.engine import session_scope
from studio.db.models import ModelProfile
from studio.db.repo.profiles import get_model_profile, seed_model_profiles
from studio.db.repo.projects import update_project_settings
from studio.db.repo.sessions import create_session, get_session
from studio.db.repo.snapshots import get_snapshot, latest_snapshot, list_snapshots
from studio.db.repo.stages import create_stage, get_stage
from studio.db.repo.turns import (
    NEVER_STARTED_ERROR,
    TurnValue,
    create_turn_if_session_idle,
    get_turn,
    list_events,
    mark_turn_running,
)
from studio.workspace import WriteScope, files, rollback

from .conftest import StudioEnv

Script = list[FakeStep] | Callable[[], AgentRuntime]


class RecordingFake(FakeRuntime):
    """FakeRuntime that records the TurnContext it was given."""

    def __init__(self, script: list[FakeStep], sink: list[TurnContext]) -> None:
        super().__init__(script)
        self._sink = sink

    async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
        self._sink.append(ctx)
        async for event in super().run_turn(ctx):
            yield event


@dataclass
class Harness:
    env: StudioEnv
    runner: TurnRunner
    bus: SessionBus
    scripts: deque[Script]
    contexts: list[TurnContext]

    def session(self, stage: str = "topic", project_id: str | None = None, profile="fake") -> str:
        value = get_model_profile(self.env.engine, profile)
        assert value is not None
        return create_session(
            self.env.engine,
            project_id=project_id or self.env.project_id,
            stage=stage,
            model_profile_id=value.id,
            runtime="fake",
        ).id

    async def run(self, session_id: str, script: Script, text: str = "你好") -> TurnValue:
        self.scripts.append(script)
        turn_id = await self.runner.start_turn(session_id, UserInput(text=text))
        await asyncio.wait_for(self.runner.wait(turn_id), timeout=5)
        turn = get_turn(self.env.engine, turn_id)
        assert turn is not None
        return turn

    @property
    def last_prompt(self) -> str:
        return self.contexts[-1].user_input.text


def _make_harness(
    env: StudioEnv, *, max_concurrent_turns: int = 2, web_mode: Literal["tools", "native"] = "tools"
) -> Harness:
    seed_model_profiles(env.engine, enable_fake_runtime=True)
    scripts: deque[Script] = deque()
    contexts: list[TurnContext] = []

    def construct() -> AgentRuntime:
        script = scripts.popleft()
        if callable(script):
            return script()
        return RecordingFake(script, contexts)

    factory = RuntimeFactory()
    factory.register("fake", construct)
    bus = SessionBus()
    settings = Settings(
        data_dir=env.data_dir, max_concurrent_turns=max_concurrent_turns, web_mode=web_mode
    )
    runner = TurnRunner(env.engine, env.blobs, env.registry, factory, bus, settings)
    return Harness(env, runner, bus, scripts, contexts)


@pytest.fixture
def h(env: StudioEnv) -> Harness:
    return _make_harness(env)


def _collect(bus: SessionBus, session_id: str) -> tuple[list[BusEvent], asyncio.Task[None]]:
    received: list[BusEvent] = []
    stream = bus.subscribe(session_id)

    async def pump() -> None:
        async for event in stream:
            received.append(event)

    return received, asyncio.create_task(pump())


async def _drain(task: asyncio.Task[None]) -> None:
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def _until(predicate: Callable[[], bool]) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


def _set_profile_limits(env: StudioEnv, **limits: Any) -> None:
    with session_scope(env.engine) as db:
        db.add(
            ModelProfile(name="limited", provider="fake", model="fake", runtime="fake", **limits)
        )


class TestNormalTurn:
    async def test_events_persisted_published_and_snapshotted(self, h: Harness) -> None:
        session_id = h.session()
        received, pump = _collect(h.bus, session_id)

        turn = await h.run(session_id, [fake.say("好的"), fake.write("topic/brief.md", "v1")])
        await _drain(pump)

        assert turn.status == "done"
        rows = list_events(h.env.engine, session_id)
        row_types = [r.type for r in rows]
        # TD-10：断言相对顺序和不变量，而不是绑定完整的事件类型列表——runner
        # 按 T6/T7 拆分模块时，没有因果关系的事件谁先持久化是实现细节。
        assert type_counts(row_types) == Counter(
            {"text": 1, "tool_call": 1, "tool_result": 1, "snapshot": 1}
        )
        # 因果链：说话 → 调工具 → 工具结果 → 快照（快照必须在 turn_end 之前，
        # 这里体现为它是持久化事件里最后被记的一条）。
        assert_in_order(row_types, "text", "tool_call", "tool_result", "snapshot")
        # 持久化的 seq 必须连续单调，从 1 开始。
        assert [r.seq for r in rows] == [1, 2, 3, 4]
        assert rows[0].payload == {"turn_id": turn.id, "text": "好的"}

        assert turn.end_snapshot_id is not None
        end = get_snapshot(h.env.engine, turn.end_snapshot_id)
        assert end is not None and end.reason == "turn" and end.turn_id == turn.id
        assert "topic/brief.md" in end.manifest
        assert rows[-1].payload["snapshot_id"] == end.id
        assert turn.start_snapshot_id is not None

        persistent = [e for e in received if not e.is_transient]
        assert [(e.type, e.seq) for e in persistent] == [(r.type, r.seq) for r in rows]
        changed = [e for e in received if e.type == "workspace_changed"]
        assert [e.payload["paths"] for e in changed] == [["topic/brief.md"]]
        statuses = [e.payload["status"] for e in received if e.type == "turn_status"]
        assert statuses == ["queued", "running", "done"]
        # the done status is published after the snapshot event
        assert received.index(persistent[-1]) < max(
            i for i, e in enumerate(received) if e.type == "turn_status"
        )

        session = get_session(h.env.engine, session_id)
        assert session is not None and session.status == "idle"
        assert h.contexts[0].system_prompt  # stage prompt is passed through

    async def test_seq_is_continuous_across_turns(self, h: Harness) -> None:
        session_id = h.session()
        await h.run(session_id, [fake.say("1")])
        await h.run(session_id, [fake.say("2"), fake.write("topic/a.md", "a")])

        seqs = [r.seq for r in list_events(h.env.engine, session_id)]
        assert seqs == list(range(1, len(seqs) + 1))


class TestThinking:
    async def test_block_is_persisted_and_delta_is_published_only(self, h: Harness) -> None:
        session_id = h.session()
        received, pump = _collect(h.bus, session_id)

        turn = await h.run(session_id, [fake.think("先想一想"), fake.say("好")])
        await _drain(pump)

        rows = list_events(h.env.engine, session_id)
        row_types = [r.type for r in rows]
        assert type_counts(row_types)["thinking"] == 1
        assert "thinking_delta" not in row_types
        assert_in_order(row_types, "thinking", "text")
        thinking = next(r for r in rows if r.type == "thinking")
        assert thinking.payload == {"turn_id": turn.id, "text": "先想一想"}
        deltas = [e for e in received if e.type == "thinking_delta"]
        assert deltas and all(e.is_transient and e.seq is None for e in deltas)
        assert "".join(e.payload["text"] for e in deltas) == "先想一想"

    async def test_thinking_does_not_count_as_a_step(self, env: StudioEnv) -> None:
        _set_profile_limits(env, max_steps_per_turn=1)
        h = _make_harness(env)
        session_id = h.session(profile="limited")

        turn = await h.run(
            session_id, [fake.think("想"), fake.think("再想"), fake.write("topic/a.md", "a")]
        )

        assert turn.status == "done"

    async def test_blank_thinking_is_dropped(self, h: Harness) -> None:
        class BlankThinking:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                yield events.ThinkingDelta(text="  \n")
                yield events.ThinkingBlock(text="   ")
                yield events.ThinkingBlock(text="")
                yield events.TextBlock(text="好")
                yield events.TurnEnd(resume_ref=None, status="done")

        session_id = h.session()
        received, pump = _collect(h.bus, session_id)

        await h.run(session_id, BlankThinking)
        await _drain(pump)

        assert "thinking" not in [r.type for r in list_events(h.env.engine, session_id)]
        assert not [e for e in received if e.type == "thinking_delta"]


class TestFailureAndCancel:
    async def test_failed_turn_takes_partial_snapshot(self, h: Harness) -> None:
        session_id = h.session()
        turn = await h.run(session_id, [fake.write("topic/brief.md", "wip"), fake.fail("限流")])

        assert (turn.status, turn.error) == ("failed", "限流")
        end = get_snapshot(h.env.engine, turn.end_snapshot_id or "")
        assert end is not None and end.reason == "partial" and "topic/brief.md" in end.manifest
        types = [r.type for r in list_events(h.env.engine, session_id)]
        assert types[-2:] == ["error", "snapshot"]

    async def test_runtime_exception_is_failed_with_partial_snapshot(self, h: Harness) -> None:
        class Exploding:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                files.write_text(ctx.workdir, "topic/brief.md", "wip", ctx.write_scope)
                yield events.TextBlock(text="写了一半")
                raise RuntimeError("网络断开")

        session_id = h.session()
        turn = await h.run(session_id, Exploding)

        assert turn.status == "failed" and "网络断开" in (turn.error or "")
        end = get_snapshot(h.env.engine, turn.end_snapshot_id or "")
        assert end is not None and end.reason == "partial" and "topic/brief.md" in end.manifest
        session = get_session(h.env.engine, session_id)
        assert session is not None and session.status == "idle"

    async def test_cancel_running_turn(self, h: Harness) -> None:
        session_id = h.session()
        h.scripts.append(
            [fake.write("topic/a.md", "a"), fake.sleep(5), fake.write("topic/b.md", "b")]
        )
        turn_id = await h.runner.start_turn(session_id, UserInput(text="go"))
        await _until(
            lambda: any(r.type == "tool_result" for r in list_events(h.env.engine, session_id))
        )

        assert h.runner.cancel(turn_id) is True
        await asyncio.wait_for(h.runner.wait(turn_id), timeout=5)

        turn = get_turn(h.env.engine, turn_id)
        assert turn is not None and turn.status == "cancelled"
        end = get_snapshot(h.env.engine, turn.end_snapshot_id or "")
        assert end is not None and end.reason == "turn"
        assert "topic/a.md" in end.manifest and "topic/b.md" not in end.manifest


class TestBudget:
    async def test_step_budget_enforced_by_runner(self, env: StudioEnv) -> None:
        h = _make_harness(env)
        _set_profile_limits(env, max_steps_per_turn=2)

        class Chatty:
            """Ignores ctx.budget: only the runner can stop it."""

            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                for i in range(100):
                    if ctx.cancel_token.is_cancelled:
                        yield events.TurnEnd(resume_ref=None, status="cancelled")
                        return
                    yield events.ToolCall(call_id=f"c{i}", name="noop", args={})
                    yield events.ToolResult(call_id=f"c{i}", text="ok")
                yield events.TurnEnd(resume_ref=None, status="done")

        session_id = h.session(profile="limited")
        turn = await h.run(session_id, Chatty)

        assert turn.status == "budget_exceeded"
        calls = [r for r in list_events(env.engine, session_id) if r.type == "tool_call"]
        assert len(calls) == 3
        assert turn.usage is not None and turn.usage["steps"] == 3

    async def test_step_budget_stops_fake_runtime(self, env: StudioEnv) -> None:
        """TD-18: moved from the runtime tests. The runner counts steps and cancels
        the token; the runtime ends `cancelled`, the turn is `budget_exceeded`."""
        h = _make_harness(env)
        _set_profile_limits(env, max_steps_per_turn=1)
        session_id = h.session(profile="limited")

        turn = await h.run(
            session_id,
            [
                fake.write("topic/a.md", "a"),
                fake.write("topic/b.md", "b"),
                fake.write("topic/c.md", "c"),
            ],
        )

        assert turn.status == "budget_exceeded"
        calls = [r for r in list_events(env.engine, session_id) if r.type == "tool_call"]
        assert len(calls) == 2
        assert not (env.workdir / "topic" / "c.md").exists()

    async def test_cost_budget(self, env: StudioEnv) -> None:
        h = _make_harness(env)
        _set_profile_limits(env, max_cost_per_turn=1.0)
        session_id = h.session(profile="limited")

        turn = await h.run(
            session_id, [fake.use_cost(0.6), fake.use_cost(0.6), fake.write("topic/a.md", "a")]
        )

        assert turn.status == "budget_exceeded"
        assert turn.cost_usd == pytest.approx(1.2)
        assert turn.end_snapshot_id is not None

    async def test_carryover_usage_does_not_trigger_cost_budget(self, env: StudioEnv) -> None:
        """TD-25: the residual of a previously aborted turn cannot be separated from this
        turn's own cost, so a Usage that includes it is not judged against the budget."""
        h = _make_harness(env)
        _set_profile_limits(env, max_cost_per_turn=1.0)

        class AfterAbort:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                yield events.Usage(
                    input_tokens=10,
                    output_tokens=10,
                    cost_usd=5.0,
                    auth="api_key",
                    includes_carryover=True,
                )
                yield events.TurnEnd(resume_ref=None, status="done")

        session_id = h.session(profile="limited")
        turn = await h.run(session_id, AfterAbort)

        assert turn.status == "done"
        assert turn.cost_usd == pytest.approx(5.0)
        assert turn.usage is not None and turn.usage["includes_carryover"] is True
        notices = [r.payload for r in list_events(env.engine, session_id) if r.type == "notice"]
        assert [n["kind"] for n in notices] == ["cost_carryover"]

    async def test_turn_usage_records_cache_read_tokens(self, env: StudioEnv) -> None:
        h = _make_harness(env)

        class Cached:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                for _ in range(2):
                    yield events.Usage(
                        input_tokens=100, output_tokens=5, cost_usd=0.0, cache_read_tokens=60
                    )
                yield events.TurnEnd(resume_ref=None, status="done")

        turn = await h.run(h.session(), Cached)

        assert turn.usage is not None
        assert (turn.usage["input_tokens"], turn.usage["cache_read_tokens"]) == (200, 120)

    async def test_usage_without_carryover_has_no_carryover_flag(self, env: StudioEnv) -> None:
        h = _make_harness(env)
        session_id = h.session()

        turn = await h.run(session_id, [fake.use_cost(0.1)])

        assert turn.usage is not None and turn.usage["includes_carryover"] is False

    async def test_cost_is_advisory_for_login_auth(self, env: StudioEnv) -> None:
        h = _make_harness(env)
        _set_profile_limits(env, max_cost_per_turn=1.0)

        class Subscription:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                yield events.Usage(input_tokens=10, output_tokens=10, cost_usd=5.0, auth="login")
                yield events.TurnEnd(resume_ref=None, status="done")

        turn = await h.run(h.session(profile="limited"), Subscription)

        assert turn.status == "done"
        assert turn.cost_usd == pytest.approx(5.0)

    async def test_unpriced_usage_emits_one_notice_and_no_cost(self, env: StudioEnv) -> None:
        h = _make_harness(env)

        class Unpriced:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                for _ in range(2):
                    yield events.Usage(
                        input_tokens=10, output_tokens=5, cost_usd=0.0, auth="api_key", priced=False
                    )
                yield events.TurnEnd(resume_ref=None, status="done")

        session_id = h.session()
        turn = await h.run(session_id, Unpriced)

        assert turn.status == "done"
        assert turn.cost_usd is None
        notices = [r.payload for r in list_events(env.engine, session_id) if r.type == "notice"]
        assert [n["kind"] for n in notices] == ["cost_unpriced"]
        assert turn.usage is not None and turn.usage["input_tokens"] == 20


class TestWorkspaceChangedPaths:
    async def test_move_to_target_is_published(self, h: Harness) -> None:
        class Mover:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                args: dict[str, object] = {
                    "type": "update_file",
                    "path": "topic/a.md",
                    "move_to": "topic/b.md",
                }
                yield events.ToolCall(call_id="p1", name="apply_patch", args=args)
                yield events.ToolResult(call_id="p1", text="ok")
                yield events.TurnEnd(resume_ref=None, status="done")

        session_id = h.session()
        received, pump = _collect(h.bus, session_id)
        await h.run(session_id, Mover)
        await _drain(pump)

        changed = [e.payload["paths"] for e in received if e.type == "workspace_changed"]
        assert changed == [["topic/a.md", "topic/b.md"]]

    async def test_claude_native_file_path_is_published(self, h: Harness) -> None:
        # TD-13: Claude's native Write/Edit tools use `file_path`, not `path`.
        class ClaudeWriter:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                args: dict[str, object] = {"file_path": "topic/a.md", "content": "x"}
                yield events.ToolCall(call_id="c1", name="Write", args=args)
                yield events.ToolResult(call_id="c1", text="ok")
                yield events.TurnEnd(resume_ref=None, status="done")

        session_id = h.session()
        received, pump = _collect(h.bus, session_id)
        await h.run(session_id, ClaudeWriter)
        await _drain(pump)

        changed = [e.payload["paths"] for e in received if e.type == "workspace_changed"]
        assert changed == [["topic/a.md"]]

    async def test_claude_notebook_edit_path_is_published(self, h: Harness) -> None:
        class ClaudeNotebookEditor:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                args: dict[str, object] = {"notebook_path": "topic/nb.ipynb"}
                yield events.ToolCall(call_id="n1", name="NotebookEdit", args=args)
                yield events.ToolResult(call_id="n1", text="ok")
                yield events.TurnEnd(resume_ref=None, status="done")

        session_id = h.session()
        received, pump = _collect(h.bus, session_id)
        await h.run(session_id, ClaudeNotebookEditor)
        await _drain(pump)

        changed = [e.payload["paths"] for e in received if e.type == "workspace_changed"]
        assert changed == [["topic/nb.ipynb"]]

    async def test_candidate_path_deduped_against_recorded(self, h: Harness) -> None:
        # A native file tool's `file_path` can name the same path
        # `record_tool_write` already recorded; the published list must not
        # repeat it (TD-13/TD-8: merge then dedupe, preserving order).
        class DupWriter:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                target = Path(ctx.workdir) / "topic" / "a.md"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("x", encoding="utf-8")
                ctx.record_tool_write("topic/a.md", "unused")
                yield events.ToolCall(call_id="c1", name="Write", args={"file_path": "topic/a.md"})
                yield events.ToolResult(call_id="c1", text="ok")
                yield events.TurnEnd(resume_ref=None, status="done")

        session_id = h.session()
        received, pump = _collect(h.bus, session_id)
        turn = await h.run(session_id, DupWriter)
        await _drain(pump)

        assert turn.status == "done"
        changed = [e.payload["paths"] for e in received if e.type == "workspace_changed"]
        assert changed == [["topic/a.md"]]


class TestAllowWeb:
    async def test_native_mode_allow_web_follows_stage_definition(self, env: StudioEnv) -> None:
        h = _make_harness(env, web_mode="native")
        await h.run(h.session(stage="topic"), [fake.say("a")])
        await h.run(h.session(stage="narrative"), [fake.say("b")])

        assert [ctx.allow_web for ctx in h.contexts] == [True, False]


class TestEffort:
    async def test_effort_comes_from_project_settings(self, env: StudioEnv) -> None:
        h = _make_harness(env)
        update_project_settings(env.engine, env.project_id, {"effort": "low"})

        await h.run(h.session(), [fake.say("a")])

        assert [ctx.effort for ctx in h.contexts] == ["low"]

    async def test_missing_or_invalid_effort_falls_back_to_default(self, env: StudioEnv) -> None:
        h = _make_harness(env)
        await h.run(h.session(), [fake.say("a")])
        update_project_settings(env.engine, env.project_id, {"effort": "bogus"})
        await h.run(h.session(), [fake.say("b")])

        assert [ctx.effort for ctx in h.contexts] == [DEFAULT_EFFORT, DEFAULT_EFFORT]


class TestResumeAndTruncation:
    async def test_resume_ref_saved_and_tool_result_truncated(self, h: Harness) -> None:
        seen: list[str | None] = []

        class Resumable:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                seen.append(ctx.resume_ref)
                yield events.ToolCall(call_id="c1", name="noop", args={})
                yield events.ToolResult(call_id="c1", text="x" * (TOOL_RESULT_MAX_CHARS + 50))
                yield events.TurnEnd(resume_ref="sdk-42", status="done")

        session_id = h.session()
        await h.run(session_id, Resumable)
        await h.run(session_id, Resumable)

        assert seen == [None, "sdk-42"]
        session = get_session(h.env.engine, session_id)
        assert session is not None and session.sdk_ref == "sdk-42"
        result = next(r for r in list_events(h.env.engine, session_id) if r.type == "tool_result")
        assert len(result.payload["text"]) < TOOL_RESULT_MAX_CHARS + 50
        assert result.payload["truncated"] is True

    async def test_nested_tool_call_args_are_truncated(self, h: Harness) -> None:
        # TD-8: `_truncate_args` must recurse into dict/list values, not just
        # top-level strings.
        long = "y" * (TOOL_RESULT_MAX_CHARS + 50)

        class NestedArgs:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                args: dict[str, object] = {
                    "path": "topic/a.md",
                    "edits": [{"old": long, "new": [long, {"deep": long}]}],
                }
                yield events.ToolCall(call_id="c1", name="edit_file", args=args)
                yield events.ToolResult(call_id="c1", text="ok")
                yield events.TurnEnd(resume_ref=None, status="done")

        session_id = h.session()
        await h.run(session_id, NestedArgs)

        call = next(r for r in list_events(h.env.engine, session_id) if r.type == "tool_call")
        edits = call.payload["args"]["edits"]
        assert len(edits[0]["old"]) < len(long)
        assert len(edits[0]["new"][0]) < len(long)
        assert len(edits[0]["new"][1]["deep"]) < len(long)


class TestGuard:
    async def test_shell_out_of_scope_restored_and_reported_next_turn(self, h: Harness) -> None:
        session_id = h.session()
        received, pump = _collect(h.bus, session_id)

        turn = await h.run(
            session_id,
            [fake.shell_write("style/STYLE.md", "被改了"), fake.write("topic/brief.md", "ok")],
        )
        await _drain(pump)

        assert (h.env.workdir / "style" / "STYLE.md").read_text(encoding="utf-8") == "# 风格\n"
        notices = [r for r in list_events(h.env.engine, session_id) if r.type == "notice"]
        assert notices[0].payload["paths"] == ["style/STYLE.md"]
        assert turn.status == "done"
        assert any(
            e.type == "workspace_changed" and e.payload["paths"] == ["style/STYLE.md"]
            for e in received
        )
        # shell calls publish an "unknown paths" change
        assert any(e.type == "workspace_changed" and e.payload["paths"] == [] for e in received)

        await h.run(session_id, [fake.say("嗯")])
        assert "被还原" in h.last_prompt and "style/STYLE.md" in h.last_prompt

    async def test_write_into_upstream_is_restored(self, h: Harness) -> None:
        h.env.write("topic/brief.md", "定稿简报")
        finalize(h.env.engine, h.env.blobs, h.env.registry, h.env.project_id, "topic")
        session_id = h.session(stage="narrative")

        await h.run(session_id, [fake.shell_write("upstream/topic/evil.md", "x")])

        upstream = h.env.workdir / "upstream" / "topic"
        assert (upstream / "brief.md").read_text(encoding="utf-8") == "定稿简报"
        assert not (upstream / "evil.md").exists()

        await h.run(session_id, [fake.say("嗯")])
        assert "被还原" in h.last_prompt and "upstream/topic/evil.md" in h.last_prompt

    async def test_business_tool_write_to_tool_managed_file_survives_guard(
        self, h: Harness
    ) -> None:
        class NoArgs(BaseModel):
            pass

        def make_timing(ctx: ToolContext, _args: NoArgs) -> ToolResult:
            files.write_text_unscoped(ctx.workdir, "narrative/timing.json", "{}")
            sha = h.env.blobs.put(b"{}")
            ctx.record_tool_write("narrative/timing.json", sha)
            return ToolResult(text="ok")

        class NarrativeWithTool:
            name = "narrative"

            def __init__(self) -> None:
                self._base = h.env.registry.get("narrative")

            allow_web = False
            workspaceless = False

            def finalize_blockers(self, workdir: Path) -> list[str]:
                return []

            def system_prompt(self) -> str:
                return "p"

            def tools(self) -> list[ToolSpec]:
                return [ToolSpec("make_timing", "d", NoArgs, {"narrative"}, make_timing)]

            def write_scope(self) -> WriteScope:
                return self._base.write_scope()

            def reads(self) -> list[str]:
                return ["topic"]

            def prepare_turn(self, workdir: Path) -> None:
                return None

            def artifact_dirs(self) -> list[str]:
                return ["narrative"]

            def status_summary(self, workdir: Path) -> str:
                return ""

        h.env.registry.register(NarrativeWithTool())
        session_id = h.session(stage="narrative")
        received, pump = _collect(h.bus, session_id)

        turn = await h.run(session_id, [fake.call_tool("make_timing")])
        await _drain(pump)

        assert turn.status == "done"
        timing = h.env.workdir / "narrative" / "timing.json"
        assert timing.read_text(encoding="utf-8") == "{}"
        assert any(
            e.type == "workspace_changed" and e.payload["paths"] == ["narrative/timing.json"]
            for e in received
        )

    async def test_tool_context_carries_the_runner_engine(self, h: Harness) -> None:
        # TD-32: business tools that need to write to the DB (e.g.
        # `suggest_upstream_change`) read it off `ToolContext.engine`, wired
        # by `TurnRunner` from the same `Engine` it was constructed with.
        seen_engines = []

        class NoArgs(BaseModel):
            pass

        def record_engine(ctx: ToolContext, _args: NoArgs) -> ToolResult:
            seen_engines.append(ctx.engine)
            return ToolResult(text="ok")

        class TopicWithTool:
            name = "topic"
            allow_web = False
            workspaceless = False

            def finalize_blockers(self, workdir: Path) -> list[str]:
                return []

            def __init__(self) -> None:
                self._base = h.env.registry.get("topic")

            def system_prompt(self) -> str:
                return "p"

            def tools(self) -> list[ToolSpec]:
                return [ToolSpec("record_engine", "d", NoArgs, {"topic"}, record_engine)]

            def write_scope(self) -> WriteScope:
                return self._base.write_scope()

            def reads(self) -> list[str]:
                return []

            def prepare_turn(self, workdir: Path) -> None:
                return None

            def artifact_dirs(self) -> list[str]:
                return ["topic"]

            def status_summary(self, workdir: Path) -> str:
                return ""

        h.env.registry.register(TopicWithTool())
        session_id = h.session(stage="topic")

        turn = await h.run(session_id, [fake.call_tool("record_engine")])

        assert turn.status == "done"
        assert seen_engines == [h.env.engine]


class TestToolResultImages:
    # TD-21: tool_result images used to persist only `media_type`; now the
    # bytes go into the blob store and the event carries a `sha256` back
    # reference so the frontend can fetch them.
    async def test_image_bytes_are_persisted_to_the_blob_store(self, h: Harness) -> None:
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
        image = events.ImageData(
            media_type="image/png",
            data_base64=base64.b64encode(png_bytes).decode("ascii"),
        )

        class NoArgs(BaseModel):
            pass

        def return_image(ctx: ToolContext, _args: NoArgs) -> ToolResult:
            return ToolResult(text="ok", images=[image])

        class TopicWithImageTool:
            name = "topic"
            allow_web = False
            workspaceless = False

            def finalize_blockers(self, workdir: Path) -> list[str]:
                return []

            def __init__(self) -> None:
                self._base = h.env.registry.get("topic")

            def system_prompt(self) -> str:
                return "p"

            def tools(self) -> list[ToolSpec]:
                return [ToolSpec("return_image", "d", NoArgs, {"topic"}, return_image)]

            def write_scope(self) -> WriteScope:
                return self._base.write_scope()

            def reads(self) -> list[str]:
                return []

            def prepare_turn(self, workdir: Path) -> None:
                return None

            def artifact_dirs(self) -> list[str]:
                return ["topic"]

            def status_summary(self, workdir: Path) -> str:
                return ""

        h.env.registry.register(TopicWithImageTool())
        session_id = h.session(stage="topic")
        received, pump = _collect(h.bus, session_id)

        turn = await h.run(session_id, [fake.call_tool("return_image")])
        await _drain(pump)

        assert turn.status == "done"
        tool_result = next(e for e in received if e.type == "tool_result")
        [persisted_image] = tool_result.payload["images"]
        assert persisted_image["media_type"] == "image/png"
        assert h.env.blobs.get(persisted_image["sha256"]) == png_bytes


class TestPreambleAcrossTurns:
    async def test_user_edit_snapshot_and_preamble_diff(self, h: Harness) -> None:
        session_id = h.session()
        await h.run(session_id, [fake.write("topic/brief.md", "第一版\n")])

        h.env.write("topic/brief.md", "用户改过\n")
        turn = await h.run(session_id, [fake.say("看到了")])

        start = get_snapshot(h.env.engine, turn.start_snapshot_id or "")
        assert start is not None and start.reason == "user_edit"
        assert start.manifest["topic/brief.md"] == h.env.blobs.put("用户改过\n".encode())
        assert "用户手动修改" in h.last_prompt
        assert "topic/brief.md" in h.last_prompt and "+用户改过" in h.last_prompt
        assert h.last_prompt.endswith("你好")

    async def test_no_changes_means_no_user_edit_section(self, h: Harness) -> None:
        session_id = h.session()
        await h.run(session_id, [fake.write("topic/brief.md", "v1")])
        await h.run(session_id, [fake.say("ok")])

        assert "用户手动修改" not in h.last_prompt
        assert (
            sum(
                1 for s in list_snapshots(h.env.engine, h.env.project_id) if s.reason == "user_edit"
            )
            == 0
        )

    async def test_rollback_notice(self, h: Harness) -> None:
        session_id = h.session()
        first = await h.run(session_id, [fake.write("topic/brief.md", "v1")])
        await h.run(session_id, [fake.write("topic/brief.md", "v2"), fake.write("topic/x.md", "x")])

        rollback(h.env.engine, h.env.blobs, h.env.project_id, first.end_snapshot_id or "")
        await h.run(session_id, [fake.say("ok")])

        assert "回滚" in h.last_prompt
        assert str(first.end_snapshot_id) in h.last_prompt
        assert "topic/x.md" in h.last_prompt

        # the notice is not repeated on the following turn
        await h.run(session_id, [fake.say("ok")])
        assert "回滚" not in h.last_prompt

    async def test_new_session_gets_handoff_summary(self, h: Harness) -> None:
        await h.run(h.session(), [fake.write("topic/brief.md", "v1")])

        await h.run(h.session(), [fake.say("接着来")])

        assert "会话交接" in h.last_prompt and "topic/brief.md" in h.last_prompt

    async def test_stale_downstream_sees_upstream_change_then_becomes_active(
        self, h: Harness
    ) -> None:
        engine, blobs, registry, pid = h.env.engine, h.env.blobs, h.env.registry, h.env.project_id
        h.env.write("topic/brief.md", "v1")
        finalize(engine, blobs, registry, pid, "topic")
        reopen(engine, pid, "topic")
        h.env.write("topic/brief.md", "v2")
        finalize(engine, blobs, registry, pid, "topic")
        stage = get_stage(engine, pid, "narrative")
        assert stage is not None and stage.status == "stale"

        await h.run(h.session(stage="narrative"), [fake.say("收到")])

        assert "上游新定稿" in h.last_prompt and "topic/brief.md" in h.last_prompt
        assert (h.env.workdir / "upstream" / "topic" / "brief.md").read_text() == "v2"
        topic = get_stage(engine, pid, "topic")
        stage = get_stage(engine, pid, "narrative")
        assert topic is not None and stage is not None
        assert (stage.status, stage.based_on) == (
            "active",
            {"topic": topic.finalized_snapshot_id},
        )


class TestConcurrency:
    async def test_session_busy(self, h: Harness) -> None:
        session_id = h.session()
        h.scripts.append([fake.sleep(5)])
        turn_id = await h.runner.start_turn(session_id, UserInput(text="1"))

        with pytest.raises(SessionBusyError):
            await h.runner.start_turn(session_id, UserInput(text="2"))

        h.runner.cancel(turn_id)
        await h.runner.wait(turn_id)

    async def test_global_limit_queues_fifo(self, env: StudioEnv) -> None:
        h = _make_harness(env, max_concurrent_turns=1)
        other_project = env.new_project()
        first_session = h.session()
        second_session = h.session(project_id=other_project)

        h.scripts.extend([[fake.sleep(5)], [fake.say("第二个")]])
        first = await h.runner.start_turn(first_session, UserInput(text="1"))
        second = await h.runner.start_turn(second_session, UserInput(text="2"))
        await _until(lambda: (get_turn(env.engine, first) or _never()).status == "running")
        assert (get_turn(env.engine, second) or _never()).status == "queued"

        h.runner.cancel(first)
        await asyncio.wait_for(h.runner.wait(second), timeout=5)
        assert (get_turn(env.engine, second) or _never()).status == "done"

    async def test_turns_of_same_project_never_overlap(self, h: Harness) -> None:
        topic = h.session()
        h.env.write("topic/brief.md", "v1")
        finalize(h.env.engine, h.env.blobs, h.env.registry, h.env.project_id, "topic")
        narrative = h.session(stage="narrative")

        h.scripts.extend([[fake.sleep(5)], [fake.say("叙事")]])
        first = await h.runner.start_turn(topic, UserInput(text="1"))
        second = await h.runner.start_turn(narrative, UserInput(text="2"))
        await asyncio.sleep(0.05)
        assert (get_turn(h.env.engine, second) or _never()).status == "queued"
        assert h.runner.is_project_busy(h.env.project_id)

        h.runner.cancel(first)
        await asyncio.wait_for(h.runner.wait(second), timeout=5)
        assert (get_turn(h.env.engine, second) or _never()).status == "done"

    async def test_cancel_queued_turn(self, env: StudioEnv) -> None:
        h = _make_harness(env, max_concurrent_turns=1)
        first_session = h.session()
        second_session = h.session(project_id=env.new_project())
        h.scripts.append([fake.sleep(5)])
        first = await h.runner.start_turn(first_session, UserInput(text="1"))
        second = await h.runner.start_turn(second_session, UserInput(text="2"))

        assert h.runner.cancel(second) is True
        await h.runner.wait(second)
        turn = get_turn(env.engine, second)
        assert turn is not None and (turn.status, turn.end_snapshot_id) == ("cancelled", None)

        h.runner.cancel(first)
        await h.runner.wait(first)


def _never() -> TurnValue:
    raise AssertionError("turn missing")


class TestRecovery:
    def test_running_and_queued_turns_become_interrupted(self, h: Harness) -> None:
        running_session = h.session()
        queued_session = h.session(stage="narrative")
        running = create_turn_if_session_idle(h.env.engine, running_session, "1")
        queued = create_turn_if_session_idle(h.env.engine, queued_session, "2")
        assert running is not None and queued is not None
        mark_turn_running(h.env.engine, running.id, start_snapshot_id=None)
        h.env.write("topic/brief.md", "写了一半")

        h.runner.recover_on_startup()

        running_after = get_turn(h.env.engine, running.id)
        queued_after = get_turn(h.env.engine, queued.id)
        assert running_after is not None and queued_after is not None
        assert running_after.status == queued_after.status == "interrupted"
        # TD-19: only the turn that never started is marked as such.
        assert queued_after.error == NEVER_STARTED_ERROR
        assert running_after.error is None
        partial = get_snapshot(h.env.engine, running_after.end_snapshot_id or "")
        assert partial is not None and partial.reason == "partial"
        assert "topic/brief.md" in partial.manifest
        for session_id in (running_session, queued_session):
            session = get_session(h.env.engine, session_id)
            assert session is not None and session.status == "interrupted"

        # the session accepts a new turn afterwards
        assert create_turn_if_session_idle(h.env.engine, running_session, "继续") is not None

    def test_out_of_scope_write_is_restored_in_scope_kept(self, h: Harness) -> None:
        # TD-7: a `running` turn with a real start snapshot gets one guard()
        # restore (no tool_writes, since those live only in memory) before the
        # partial snapshot, using its stage's write_scope as the boundary.
        session_id = h.session(stage="topic")
        start = latest_snapshot(h.env.engine, h.env.project_id)
        assert start is not None
        turn = create_turn_if_session_idle(h.env.engine, session_id, "1")
        assert turn is not None
        mark_turn_running(h.env.engine, turn.id, start_snapshot_id=start.id)

        h.env.write("topic/ok.md", "范围内，保留")
        h.env.write("style/evil.md", "越界，应该被还原")

        h.runner.recover_on_startup()

        assert (h.env.workdir / "topic" / "ok.md").exists()
        assert not (h.env.workdir / "style" / "evil.md").exists()
        after = get_turn(h.env.engine, turn.id)
        assert after is not None and after.status == "interrupted"
        partial = get_snapshot(h.env.engine, after.end_snapshot_id or "")
        assert partial is not None
        assert "topic/ok.md" in partial.manifest
        assert "style/evil.md" not in partial.manifest

    def test_missing_start_snapshot_skips_guard_but_still_recovers(self, h: Harness) -> None:
        # Existing behaviour (no start_snapshot_id recorded) must keep working:
        # guard is skipped, but the partial snapshot and interrupt still happen.
        session_id = h.session(stage="topic")
        turn = create_turn_if_session_idle(h.env.engine, session_id, "1")
        assert turn is not None
        mark_turn_running(h.env.engine, turn.id, start_snapshot_id=None)

        h.env.write("style/untouched.md", "不受影响（没有起始快照可比对）")

        h.runner.recover_on_startup()

        assert (h.env.workdir / "style" / "untouched.md").exists()
        after = get_turn(h.env.engine, turn.id)
        assert after is not None and after.status == "interrupted"
        assert after.end_snapshot_id is not None


class TestShutdown:
    async def test_running_turn_is_finished_as_interrupted_with_partial_snapshot(
        self, h: Harness
    ) -> None:
        session_id = h.session()
        h.scripts.append([fake.write("topic/brief.md", "半成品"), fake.sleep(30)])
        turn_id = await h.runner.start_turn(session_id, UserInput(text="1"))
        await _until(lambda: (h.env.workdir / "topic" / "brief.md").exists())

        await asyncio.wait_for(h.runner.shutdown(), timeout=5)

        turn = get_turn(h.env.engine, turn_id)
        assert turn is not None and turn.status == "interrupted"
        partial = get_snapshot(h.env.engine, turn.end_snapshot_id or "")
        assert partial is not None and partial.reason == "partial"
        assert "topic/brief.md" in partial.manifest
        assert not h.runner.is_project_busy(h.env.project_id)

    async def test_stubborn_runtime_is_force_cancelled(self, h: Harness) -> None:
        class Stubborn:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                await asyncio.sleep(30)
                yield events.TurnEnd(resume_ref=None, status="done")

        session_id = h.session()
        h.scripts.append(Stubborn)
        turn_id = await h.runner.start_turn(session_id, UserInput(text="1"))
        await _until(lambda: h.runner.is_project_busy(h.env.project_id))
        await asyncio.sleep(0.05)

        await asyncio.wait_for(h.runner.shutdown(grace_seconds=0.05), timeout=5)

        turn = get_turn(h.env.engine, turn_id)
        assert turn is not None and turn.status == "interrupted"
        assert turn.end_snapshot_id is not None

    async def test_queued_turn_becomes_interrupted(self, env: StudioEnv) -> None:
        h = _make_harness(env, max_concurrent_turns=1)
        first_session = h.session()
        second_session = h.session(project_id=env.new_project())
        h.scripts.append([fake.sleep(30)])
        first = await h.runner.start_turn(first_session, UserInput(text="1"))
        second = await h.runner.start_turn(second_session, UserInput(text="2"))

        await asyncio.wait_for(h.runner.shutdown(), timeout=5)

        for turn_id in (first, second):
            turn = get_turn(env.engine, turn_id)
            assert turn is not None and turn.status == "interrupted", turn_id
        first_turn, second_turn = get_turn(env.engine, first), get_turn(env.engine, second)
        assert first_turn is not None and first_turn.error is None
        assert second_turn is not None and second_turn.error == NEVER_STARTED_ERROR  # TD-19
        assert not h.scripts  # the queued turn never started a runtime


class TestReviewFixes:
    async def test_budget_wins_when_grace_period_force_cancels(self, env: StudioEnv) -> None:
        h = _make_harness(env)
        _set_profile_limits(env, max_steps_per_turn=1)
        h.runner._cancel_grace_seconds = 0.05

        class Stubborn:
            """Ignores the cancel token entirely."""

            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                for i in range(3):
                    yield events.ToolCall(call_id=f"c{i}", name="noop", args={})
                    yield events.ToolResult(call_id=f"c{i}", text="ok")
                await asyncio.sleep(5)
                yield events.TurnEnd(resume_ref=None, status="done")

        turn = await h.run(h.session(profile="limited"), Stubborn)

        assert turn.status == "budget_exceeded"
        assert turn.end_snapshot_id is not None

    async def test_user_edit_absorbed_by_finalize_still_reported(self, h: Harness) -> None:
        session_id = h.session()
        await h.run(session_id, [fake.write("topic/brief.md", "v1\n")])
        h.env.write("topic/brief.md", "用户改过\n")
        finalize(h.env.engine, h.env.blobs, h.env.registry, h.env.project_id, "topic")
        reopen(h.env.engine, h.env.project_id, "topic")

        await h.run(session_id, [fake.say("ok")])

        assert "用户手动修改" in h.last_prompt and "+用户改过" in h.last_prompt

    async def test_user_edit_absorbed_by_other_stage_turn_still_reported(self, h: Harness) -> None:
        h.env.write("topic/brief.md", "v0\n")
        finalize(h.env.engine, h.env.blobs, h.env.registry, h.env.project_id, "topic")
        reopen(h.env.engine, h.env.project_id, "topic")
        topic, narrative = h.session(), h.session(stage="narrative")
        await h.run(topic, [fake.write("topic/brief.md", "v1\n")])
        h.env.write("topic/brief.md", "用户改过\n")
        await h.run(narrative, [fake.say("n")])
        h.env.write("topic/notes.md", "再改\n")

        await h.run(topic, [fake.say("t")])

        assert "+用户改过" in h.last_prompt and "topic/notes.md" in h.last_prompt
        # the narrative session's own first turn saw the edit too
        assert "用户手动修改" in h.contexts[-2].user_input.text

    async def test_edits_reported_once(self, h: Harness) -> None:
        session_id = h.session()
        await h.run(session_id, [fake.say("1")])
        h.env.write("topic/brief.md", "改\n")
        await h.run(session_id, [fake.say("2")])
        assert "用户手动修改" in h.last_prompt

        await h.run(session_id, [fake.say("3")])
        assert "用户手动修改" not in h.last_prompt

    async def test_cancelled_queued_turn_does_not_hide_previous_notices(
        self, env: StudioEnv
    ) -> None:
        h = _make_harness(env, max_concurrent_turns=1)
        session_id = h.session()
        await h.run(session_id, [fake.shell_write("style/STYLE.md", "x")])

        blocker = h.session(project_id=env.new_project())
        h.scripts.append([fake.sleep(5)])
        blocking = await h.runner.start_turn(blocker, UserInput(text="占位"))
        queued = await h.runner.start_turn(session_id, UserInput(text="排队"))
        h.runner.cancel(queued)
        await h.runner.wait(queued)
        h.runner.cancel(blocking)
        await h.runner.wait(blocking)

        await h.run(session_id, [fake.say("ok")])
        assert "style/STYLE.md" in h.last_prompt

    async def test_based_on_uses_upstream_version_seen_at_turn_start(self, h: Harness) -> None:
        engine, blobs, registry, pid = h.env.engine, h.env.blobs, h.env.registry, h.env.project_id
        h.env.write("topic/brief.md", "v1")
        finalize(engine, blobs, registry, pid, "topic")
        first = (get_stage(engine, pid, "topic") or _never_stage()).finalized_snapshot_id

        class RefinalizeMidTurn:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                reopen(engine, pid, "topic")
                h.env.write("topic/brief.md", "v2")
                finalize(engine, blobs, registry, pid, "topic")
                yield events.TurnEnd(resume_ref=None, status="done")

        await h.run(h.session(stage="narrative"), RefinalizeMidTurn)

        narrative = get_stage(engine, pid, "narrative")
        assert narrative is not None
        assert (narrative.status, narrative.based_on) == ("stale", {"topic": first})

    async def test_finish_turn_is_retried_once(
        self, h: Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studio.agent import runner as runner_module

        real = runner_module.turns_repo.finish_turn
        calls: list[int] = []

        def flaky(*args: Any, **kwargs: Any) -> Any:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("database is locked")
            return real(*args, **kwargs)

        monkeypatch.setattr(runner_module.turns_repo, "finish_turn", flaky)
        session_id = h.session()
        turn = await h.run(session_id, [fake.say("hi")])

        assert turn.status == "done" and len(calls) == 2
        session = get_session(h.env.engine, session_id)
        assert session is not None and session.status == "idle"

    async def test_runtime_stream_closed_when_runner_fails(self, h: Harness) -> None:
        closed: list[bool] = []

        class Unserializable:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                try:
                    yield events.ToolCall(call_id="c1", name="noop", args={"x": object()})
                    yield events.TurnEnd(resume_ref=None, status="done")
                finally:
                    closed.append(True)

        turn = await h.run(h.session(), Unserializable)

        assert turn.status == "failed"
        assert closed == [True]

    def test_recovery_continues_after_one_failure(
        self, h: Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from studio.agent import recovery as recovery_module

        sessions = [h.session(), h.session(stage="narrative")]
        turns = []
        for session_id in sessions:
            turn = create_turn_if_session_idle(h.env.engine, session_id, "x")
            assert turn is not None
            mark_turn_running(h.env.engine, turn.id, start_snapshot_id=None)
            turns.append(turn.id)
        real = recovery_module.create_snapshot
        calls: list[int] = []

        def flaky(*args: Any, **kwargs: Any) -> Any:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("disk full")
            return real(*args, **kwargs)

        monkeypatch.setattr(recovery_module, "create_snapshot", flaky)
        h.runner.recover_on_startup()

        second = get_turn(h.env.engine, turns[1])
        assert second is not None and second.status == "interrupted"


def _never_stage() -> Any:
    raise AssertionError("stage missing")


class _DelegatingStage:
    """Wraps a registered stage, overriding `prepare_turn` and optionally `reads`/name."""

    allow_web = False
    workspaceless = False

    def __init__(self, base: Any, *, name: str | None = None, reads: list[str] | None = None):
        self._base = base
        self.name = name or base.name
        self._reads = reads
        self.calls: list[bool] = []
        self.prepare_error: Exception | None = None

    def prepare_turn(self, workdir: Path) -> None:
        self.calls.append((workdir / "upstream" / "topic" / "brief.md").exists())
        if self.prepare_error is not None:
            raise self.prepare_error

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []

    def system_prompt(self) -> str:
        return "p"

    def tools(self) -> list[ToolSpec]:
        return []

    def write_scope(self) -> WriteScope:
        return self._base.write_scope()

    def reads(self) -> list[str]:
        return self._base.reads() if self._reads is None else list(self._reads)

    def artifact_dirs(self) -> list[str]:
        return self._base.artifact_dirs()

    def status_summary(self, workdir: Path) -> str:
        return ""


class TestPrepareTurn:
    async def test_called_once_per_turn_after_upstream_is_materialized(self, h: Harness) -> None:
        h.env.write("topic/brief.md", "选题\n")
        finalize(h.env.engine, h.env.blobs, h.env.registry, h.env.project_id, "topic")
        stage = _DelegatingStage(h.env.registry.get("narrative"))
        h.env.registry.register(stage)
        session_id = h.session(stage="narrative")

        await h.run(session_id, [fake.say("a")])
        assert stage.calls == [True]
        await h.run(session_id, [fake.say("b")])
        assert stage.calls == [True, True]

    async def test_files_derived_by_prepare_turn_are_not_reported_as_restored(
        self, h: Harness
    ) -> None:
        class _Deriving(_DelegatingStage):
            def prepare_turn(self, workdir: Path) -> None:
                derived = workdir / "upstream" / "derived.txt"
                derived.parent.mkdir(parents=True, exist_ok=True)
                derived.write_text("derived", encoding="utf-8")

        stage = _Deriving(h.env.registry.get("topic"))
        h.env.registry.register(stage)
        session_id = h.session(stage="topic")

        turn = await h.run(session_id, [fake.say("a")])

        assert turn.status == "done"
        notices = [e for e in list_events(h.env.engine, session_id) if e.type == "notice"]
        assert [n for n in notices if n.payload.get("kind") == GUARD_RESTORED_NOTICE] == []

    async def test_files_derived_by_prepare_turn_are_read_only_during_the_turn(
        self, h: Harness
    ) -> None:
        # TD-69: like the materialized copies, derived files are sealed before the agent runs.
        modes: list[int] = []

        class _Deriving(_DelegatingStage):
            def prepare_turn(self, workdir: Path) -> None:
                derived = workdir / "upstream" / "derived.txt"
                derived.parent.mkdir(parents=True, exist_ok=True)
                derived.write_text("derived", encoding="utf-8")

        class _Probe(FakeRuntime):
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                modes.append((ctx.workdir / "upstream" / "derived.txt").stat().st_mode & 0o222)
                async for event in super().run_turn(ctx):
                    yield event

        h.env.registry.register(_Deriving(h.env.registry.get("topic")))

        turn = await h.run(h.session(stage="topic"), lambda: _Probe([fake.say("a")]))

        assert turn.status == "done"
        assert modes == [0]

    async def test_failure_fails_the_turn_with_stage_name_and_message(self, h: Harness) -> None:
        stage = _DelegatingStage(h.env.registry.get("topic"))
        stage.prepare_error = ValueError("素材目录损坏")
        h.env.registry.register(stage)
        session_id = h.session(stage="topic")

        turn = await h.run(session_id, [fake.say("a")])

        assert turn.status == "failed"
        [error] = [e for e in list_events(h.env.engine, session_id) if e.type == "error"]
        assert "topic" in error.payload["message"]
        assert "素材目录损坏" in error.payload["message"]
        assert h.contexts == []

    async def test_workspaceless_stage_does_not_call_prepare_turn(self, h: Harness) -> None:
        stage = _DelegatingStage(h.env.registry.get("topic"), name="brainstorm")
        stage.workspaceless = True
        h.env.registry.register(stage)
        profile = get_model_profile(h.env.engine, "fake")
        assert profile is not None
        session_id = create_session(
            h.env.engine,
            project_id=None,
            stage="brainstorm",
            model_profile_id=profile.id,
            runtime="fake",
        ).id

        turn = await h.run(session_id, [fake.say("a")])

        assert turn.status == "done"
        assert stage.calls == []
        assert h.contexts[-1].tool_context().upstream_stages == ()

    async def test_upstream_stages_follow_the_project_pipeline(self, h: Harness) -> None:
        music = _DelegatingStage(
            h.env.registry.get("narrative"),
            name="music",
            reads=["concept", "narrative", "beatsheet"],
        )
        h.env.registry.register(music)
        project_id = h.env.new_project("讲解加配乐")
        update_project_settings(
            h.env.engine,
            project_id,
            {"pipeline": ["topic", "narrative", "music", "animation"]},
        )
        create_stage(h.env.engine, project_id=project_id, stage="music", status="active")
        session_id = h.session(stage="music", project_id=project_id)

        await h.run(session_id, [fake.say("x")])

        assert h.contexts[-1].tool_context().upstream_stages == ("narrative",)
