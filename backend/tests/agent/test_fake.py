from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import BaseModel

from studio.agent import events
from studio.agent.fake import (
    FakeRuntime,
    Say,
    Sleep,
    Write,
    default_fake_script,
    register_fake,
)
from studio.agent.runtime import Budget, CancelToken, RuntimeFactory, TurnContext, UserInput
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.db.repo.profiles import ModelProfileValue
from studio.workspace.scope import WriteScope

_FAKE_PROFILE = ModelProfileValue(
    id="fake",
    name="fake",
    provider="fake",
    model="fake",
    runtime="fake",
    base_url=None,
    api_key_env=None,
    supports_vision=False,
    price_input=None,
    price_output=None,
    max_cost_per_turn=None,
    max_steps_per_turn=None,
)


def _noop_record_tool_write(relpath: str, sha256: str) -> None:
    return None


def _make_ctx(
    workdir: Path,
    *,
    write_scope: WriteScope,
    tools: list[ToolSpec] | None = None,
    budget: Budget | None = None,
    cancel_token: CancelToken | None = None,
    project_id: str = "proj-1",
    stage: str = "topic",
    record_tool_write: Callable[[str, str], None] | None = None,
) -> TurnContext:
    return TurnContext(
        system_prompt="占位提示词",
        user_input=UserInput(text="你好"),
        tools=tools or [],
        workdir=workdir,
        model_profile=_FAKE_PROFILE,
        resume_ref=None,
        cancel_token=cancel_token or CancelToken(),
        budget=budget or Budget(),
        write_scope=write_scope,
        project_id=project_id,
        stage=stage,
        record_tool_write=record_tool_write or _noop_record_tool_write,
    )


async def _run(runtime: FakeRuntime, ctx: TurnContext) -> list[events.AgentEvent]:
    return [event async for event in runtime.run_turn(ctx)]


class TestSay:
    async def test_say_step_yields_text_block_and_ends_done(self, workdir: Path) -> None:
        from studio.agent import fake

        runtime = FakeRuntime([fake.say("你好，世界")])
        ctx = _make_ctx(workdir, write_scope=WriteScope(writable=["topic/**"], tool_managed=[]))

        result = await _run(runtime, ctx)

        assert result[0] == events.TextBlock(text="你好，世界")
        assert result[-1] == events.TurnEnd(resume_ref=None, status="done")


class TestWrite:
    async def test_write_within_scope_creates_file_and_success_result(self, workdir: Path) -> None:
        from studio.agent import fake

        runtime = FakeRuntime([fake.write("topic/brief.md", "draft")])
        ctx = _make_ctx(workdir, write_scope=WriteScope(writable=["topic/**"], tool_managed=[]))

        result = await _run(runtime, ctx)

        call, tool_result, turn_end = result
        assert isinstance(call, events.ToolCall)
        assert call.name in events.FILE_TOOL_NAMES
        assert isinstance(tool_result, events.ToolResult)
        assert tool_result.call_id == call.call_id
        assert tool_result.is_error is False
        assert (workdir / "topic" / "brief.md").read_text(encoding="utf-8") == "draft"
        assert turn_end == events.TurnEnd(resume_ref=None, status="done")

    async def test_write_out_of_scope_is_pre_intercepted_and_not_written(
        self, workdir: Path
    ) -> None:
        from studio.agent import fake

        runtime = FakeRuntime([fake.write("style/STYLE.md", "hacked")])
        ctx = _make_ctx(workdir, write_scope=WriteScope(writable=["topic/**"], tool_managed=[]))

        result = await _run(runtime, ctx)

        call, tool_result, _turn_end = result
        assert isinstance(call, events.ToolCall)
        assert isinstance(tool_result, events.ToolResult)
        assert tool_result.is_error is True
        assert not (workdir / "style" / "STYLE.md").exists()


class TestShellWrite:
    async def test_shell_write_bypasses_scope_check(self, workdir: Path) -> None:
        from studio.agent import fake

        runtime = FakeRuntime([fake.shell_write("style/STYLE.md", "hacked via shell")])
        ctx = _make_ctx(workdir, write_scope=WriteScope(writable=["topic/**"], tool_managed=[]))

        result = await _run(runtime, ctx)

        call, tool_result, _turn_end = result
        assert isinstance(call, events.ToolCall)
        assert isinstance(tool_result, events.ToolResult)
        assert tool_result.is_error is False
        assert (workdir / "style" / "STYLE.md").read_text(encoding="utf-8") == "hacked via shell"


class _GreetArgs(BaseModel):
    name: str


def _greet_handler(ctx: ToolContext, args: _GreetArgs) -> ToolResult:
    return ToolResult(text=f"你好，{args.name}")


class _RecordingArgs(BaseModel):
    relpath: str
    sha256: str


def _recording_handler(ctx: ToolContext, args: _RecordingArgs) -> ToolResult:
    ctx.record_tool_write(args.relpath, args.sha256)
    return ToolResult(text=f"project={ctx.project_id} stage={ctx.stage}")


class TestCallTool:
    async def test_call_tool_invokes_matching_spec(self, workdir: Path) -> None:
        from studio.agent import fake

        spec = ToolSpec(
            name="greet",
            description="打招呼",
            input_model=_GreetArgs,
            stages={"topic"},
            handler=_greet_handler,
        )
        runtime = FakeRuntime([fake.call_tool("greet", {"name": "小明"})])
        ctx = _make_ctx(
            workdir,
            write_scope=WriteScope(writable=["topic/**"], tool_managed=[]),
            tools=[spec],
        )

        result = await _run(runtime, ctx)

        call, tool_result, _turn_end = result
        assert isinstance(call, events.ToolCall)
        assert isinstance(tool_result, events.ToolResult)
        assert call.name == "greet"
        assert call.args == {"name": "小明"}
        assert tool_result.text == "你好，小明"
        assert tool_result.is_error is False

    async def test_call_tool_unknown_name_is_error(self, workdir: Path) -> None:
        from studio.agent import fake

        runtime = FakeRuntime([fake.call_tool("does_not_exist", {})])
        ctx = _make_ctx(workdir, write_scope=WriteScope(writable=["topic/**"], tool_managed=[]))

        result = await _run(runtime, ctx)

        _call, tool_result, _turn_end = result
        assert isinstance(tool_result, events.ToolResult)
        assert tool_result.is_error is True

    async def test_call_tool_builds_tool_context_from_turn_context(self, workdir: Path) -> None:
        """`ToolContext(project_id, stage, workdir, record_tool_write)` 必须
        取自 `ctx`（审查后修复：不再是 `FakeRuntime` 构造参数），验证
        handler 收到的 `project_id`/`stage` 和调用 `record_tool_write` 都
        来自传给 `run_turn` 的 `TurnContext`。
        """
        from studio.agent import fake

        spec = ToolSpec(
            name="record",
            description="记录一次工具写入",
            input_model=_RecordingArgs,
            stages={"narrative"},
            handler=_recording_handler,
        )
        recorded: list[tuple[str, str]] = []
        runtime = FakeRuntime(
            [fake.call_tool("record", {"relpath": "narrative/timing.json", "sha256": "abc"})]
        )
        ctx = _make_ctx(
            workdir,
            write_scope=WriteScope(writable=["narrative/narrative.json"], tool_managed=[]),
            tools=[spec],
            project_id="proj-42",
            stage="narrative",
            record_tool_write=lambda relpath, sha256: recorded.append((relpath, sha256)),
        )

        result = await _run(runtime, ctx)

        _call, tool_result, _turn_end = result
        assert isinstance(tool_result, events.ToolResult)
        assert tool_result.text == "project=proj-42 stage=narrative"
        assert recorded == [("narrative/timing.json", "abc")]


class TestFail:
    async def test_fail_step_ends_turn_as_failed_with_error(self, workdir: Path) -> None:
        from studio.agent import fake

        runtime = FakeRuntime([fake.say("在失败前说点什么"), fake.fail("出错了")])
        ctx = _make_ctx(workdir, write_scope=WriteScope(writable=["topic/**"], tool_managed=[]))

        result = await _run(runtime, ctx)

        assert result[-1] == events.TurnEnd(resume_ref=None, status="failed", error="出错了")


class TestUseCost:
    async def test_use_cost_yields_usage_event(self, workdir: Path) -> None:
        from studio.agent import fake

        runtime = FakeRuntime([fake.use_cost(0.05)])
        ctx = _make_ctx(workdir, write_scope=WriteScope(writable=["topic/**"], tool_managed=[]))

        result = await _run(runtime, ctx)

        usage = result[0]
        assert isinstance(usage, events.Usage)
        assert usage.cost_usd == 0.05


class TestSleepAndCancel:
    async def test_sleep_step_without_cancel_completes(self, workdir: Path) -> None:
        from studio.agent import fake

        runtime = FakeRuntime([fake.sleep(0), fake.say("醒了")])
        ctx = _make_ctx(workdir, write_scope=WriteScope(writable=["topic/**"], tool_managed=[]))

        result = await _run(runtime, ctx)

        assert events.TextBlock(text="醒了") in result
        assert result[-1] == events.TurnEnd(resume_ref=None, status="done")

    async def test_already_cancelled_token_stops_before_first_step(self, workdir: Path) -> None:
        from studio.agent import fake

        token = CancelToken()
        token.cancel()
        runtime = FakeRuntime([fake.say("不应该出现")])
        ctx = _make_ctx(
            workdir,
            write_scope=WriteScope(writable=["topic/**"], tool_managed=[]),
            cancel_token=token,
        )

        result = await _run(runtime, ctx)

        assert result == [events.TurnEnd(resume_ref=None, status="cancelled")]

    async def test_cancel_during_sleep_ends_turn_as_cancelled(self, workdir: Path) -> None:
        from studio.agent import fake

        token = CancelToken()
        runtime = FakeRuntime([fake.sleep(5), fake.say("不应该出现")])
        ctx = _make_ctx(
            workdir,
            write_scope=WriteScope(writable=["topic/**"], tool_managed=[]),
            cancel_token=token,
        )

        async def cancel_soon() -> None:
            await asyncio.sleep(0.05)
            token.cancel()

        asyncio.ensure_future(cancel_soon())
        result = await asyncio.wait_for(_run(runtime, ctx), timeout=2)

        assert result == [events.TurnEnd(resume_ref=None, status="cancelled")]


class TestBudget:
    async def test_max_steps_exceeded_ends_turn_as_budget_exceeded(self, workdir: Path) -> None:
        from studio.agent import fake

        runtime = FakeRuntime([fake.say("一"), fake.say("二"), fake.say("三")])
        ctx = _make_ctx(
            workdir,
            write_scope=WriteScope(writable=["topic/**"], tool_managed=[]),
            budget=Budget(max_steps=2),
        )

        result = await _run(runtime, ctx)

        assert result[-1] == events.TurnEnd(resume_ref=None, status="budget_exceeded")
        text_blocks = [e for e in result if isinstance(e, events.TextBlock)]
        assert len(text_blocks) == 2

    async def test_max_cost_exceeded_ends_turn_as_budget_exceeded(self, workdir: Path) -> None:
        from studio.agent import fake

        runtime = FakeRuntime([fake.use_cost(0.6), fake.say("不应该出现")])
        ctx = _make_ctx(
            workdir,
            write_scope=WriteScope(writable=["topic/**"], tool_managed=[]),
            budget=Budget(max_cost_usd=0.5),
        )

        result = await _run(runtime, ctx)

        assert result[-1] == events.TurnEnd(resume_ref=None, status="budget_exceeded")
        assert events.TextBlock(text="不应该出现") not in result


class TestDefaultFakeScript:
    def test_echoes_user_text_and_writes_note_in_first_writable_dir_glob(self) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])

        script = default_fake_script(scope, "帮我写选题")

        from studio.agent import fake

        assert any(isinstance(step, type(fake.say(""))) for step in script)
        write_steps = [step for step in script if isinstance(step, type(fake.write("a", "a")))]
        assert len(write_steps) == 1
        assert write_steps[0].path == "topic/fake-note.md"

    def test_uses_parent_dir_for_exact_file_pattern(self) -> None:
        from studio.agent import fake

        scope = WriteScope(
            writable=["narrative/narrative.json"], tool_managed=["narrative/timing.json"]
        )

        script = default_fake_script(scope, "继续")

        write_steps = [step for step in script if isinstance(step, type(fake.write("a", "a")))]
        assert write_steps[0].path == "narrative/fake-note.md"

    async def test_default_script_runs_end_to_end(self, workdir: Path) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        script = default_fake_script(scope, "帮我写选题")
        runtime = FakeRuntime(script)
        ctx = _make_ctx(workdir, write_scope=scope)

        result = await _run(runtime, ctx)

        assert result[-1] == events.TurnEnd(resume_ref=None, status="done")
        assert (workdir / "topic" / "fake-note.md").exists()

    async def test_zero_arg_constructor_builds_default_script_from_ctx(self, workdir: Path) -> None:
        """`FakeRuntime()`（不传脚本）必须在 `run_turn` 时才用 `ctx` 现场生成
        默认脚本，而不是构造时就固定——这是 `register_fake` 能把 `FakeRuntime`
        直接注册进 `RuntimeFactory`（零参数构造函数）的前提。
        """
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        runtime = FakeRuntime()
        ctx = _make_ctx(workdir, write_scope=scope)

        result = await _run(runtime, ctx)

        assert result[-1] == events.TurnEnd(resume_ref=None, status="done")
        assert (workdir / "topic" / "fake-note.md").read_text(encoding="utf-8") == "echo: 你好\n"


class TestRegisterFake:
    async def test_registers_fake_runtime_that_runs_default_script(self, workdir: Path) -> None:
        factory = RuntimeFactory()

        register_fake(factory)
        runtime = factory.create("fake")

        assert isinstance(runtime, FakeRuntime)
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        ctx = _make_ctx(workdir, write_scope=scope)
        result = await _run(runtime, ctx)

        assert result[-1] == events.TurnEnd(resume_ref=None, status="done")
        assert (workdir / "topic" / "fake-note.md").exists()


class TestFakeDelay:
    def test_default_script_has_no_sleep_without_delay(self) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        script = default_fake_script(scope, "x")
        assert not any(isinstance(step, Sleep) for step in script)

    def test_default_script_sleeps_between_text_and_write(self) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        script = default_fake_script(scope, "x", delay_seconds=2.5)
        assert [type(step) for step in script] == [Say, Sleep, Write]
        assert script[1] == Sleep(2.5)

    async def test_register_fake_passes_delay(self, workdir: Path) -> None:
        factory = RuntimeFactory()
        register_fake(factory, delay_seconds=0.05)
        runtime = factory.create("fake")
        assert isinstance(runtime, FakeRuntime)
        scope = WriteScope(writable=["topic/**"], tool_managed=[])

        started = time.monotonic()
        result = await _run(runtime, _make_ctx(workdir, write_scope=scope))

        assert time.monotonic() - started >= 0.05
        assert result[-1] == events.TurnEnd(resume_ref=None, status="done")

    def test_settings_default_delay_is_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from studio.config import Settings

        assert Settings().fake_delay_seconds == 0
        monkeypatch.setenv("STUDIO_FAKE_DELAY_SECONDS", "3")
        assert Settings().fake_delay_seconds == 3
