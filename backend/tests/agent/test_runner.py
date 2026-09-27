from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from studio.agent import events, fake
from studio.agent.bus import BusEvent, SessionBus
from studio.agent.fake import FakeRuntime, FakeStep
from studio.agent.runner import TOOL_RESULT_MAX_CHARS, SessionBusyError, TurnRunner
from studio.agent.runtime import AgentRuntime, RuntimeFactory, TurnContext, UserInput
from studio.agent.stage_flow import finalize, reopen
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.config import Settings
from studio.db.engine import session_scope
from studio.db.models import ModelProfile
from studio.db.repo.profiles import get_model_profile, seed_model_profiles
from studio.db.repo.sessions import create_session, get_session
from studio.db.repo.snapshots import get_snapshot, list_snapshots
from studio.db.repo.stages import get_stage
from studio.db.repo.turns import (
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


def _make_harness(env: StudioEnv, *, max_concurrent_turns: int = 2) -> Harness:
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
    settings = Settings(data_dir=env.data_dir, max_concurrent_turns=max_concurrent_turns)
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
        assert [r.type for r in rows] == ["text", "tool_call", "tool_result", "snapshot"]
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


class TestAllowWeb:
    async def test_allow_web_follows_stage_definition(self, h: Harness) -> None:
        await h.run(h.session(stage="topic"), [fake.say("a")])
        await h.run(h.session(stage="narrative"), [fake.say("b")])

        assert [ctx.allow_web for ctx in h.contexts] == [True, False]


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

            def system_prompt(self) -> str:
                return "p"

            def tools(self) -> list[ToolSpec]:
                return [ToolSpec("make_timing", "d", NoArgs, {"narrative"}, make_timing)]

            def write_scope(self) -> WriteScope:
                return self._base.write_scope()

            def upstream_stages(self) -> list[str]:
                return ["topic"]

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
        assert (stage.status, stage.based_on_snapshot_id) == ("active", topic.finalized_snapshot_id)


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
        partial = get_snapshot(h.env.engine, running_after.end_snapshot_id or "")
        assert partial is not None and partial.reason == "partial"
        assert "topic/brief.md" in partial.manifest
        for session_id in (running_session, queued_session):
            session = get_session(h.env.engine, session_id)
            assert session is not None and session.status == "interrupted"

        # the session accepts a new turn afterwards
        assert create_turn_if_session_idle(h.env.engine, running_session, "继续") is not None


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
        assert (narrative.status, narrative.based_on_snapshot_id) == ("stale", first)

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
        from studio.agent import runner as runner_module

        sessions = [h.session(), h.session(stage="narrative")]
        turns = []
        for session_id in sessions:
            turn = create_turn_if_session_idle(h.env.engine, session_id, "x")
            assert turn is not None
            mark_turn_running(h.env.engine, turn.id, start_snapshot_id=None)
            turns.append(turn.id)
        real = runner_module.create_snapshot
        calls: list[int] = []

        def flaky(*args: Any, **kwargs: Any) -> Any:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("disk full")
            return real(*args, **kwargs)

        monkeypatch.setattr(runner_module, "create_snapshot", flaky)
        h.runner.recover_on_startup()

        second = get_turn(h.env.engine, turns[1])
        assert second is not None and second.status == "interrupted"


def _never_stage() -> Any:
    raise AssertionError("stage missing")
