"""OpenAIRuntime 的测试：用 SDK 自带的 `agents.testing.ScriptedModel` 驱动真实的
`Runner.run_streamed`，不联网。
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agents import (
    ApplyPatchTool,
    FunctionTool,
    Model,
    OpenAIResponsesModel,
    RunContextWrapper,
    ShellCallData,
    ShellCommandRequest,
    ShellTool,
    WebSearchTool,
)
from agents.extensions.models.litellm_model import LitellmModel
from agents.testing import ModelCall, ModelStep, ScriptedModel, assistant_message, function_call
from agents.tool import ShellActionRequest
from agents.usage import Usage
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionShellToolCall,
    ResponseOutputItemDoneEvent,
)
from openai.types.responses.response_function_shell_tool_call import Action as ShellAction
from openai.types.responses.response_function_web_search import (
    ActionSearch,
    ResponseFunctionWebSearch,
)
from pydantic import BaseModel

from studio.agent import events
from studio.agent.openai_runtime import (
    MAX_TURNS,
    LocalShellExecutor,
    OpenAIRuntime,
    build_function_tool,
    build_model,
    max_turns,
    native_shell_supported,
    openai_client,
    register_openai,
    turn_cost,
)
from studio.agent.runtime import Budget, CancelToken, RuntimeFactory, TurnContext, UserInput
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.config import Settings
from studio.db.repo.profiles import ModelProfileValue
from studio.workspace.scope import WriteScope

_OPENAI = ModelProfileValue(
    id="p-gpt",
    name="gpt",
    provider="openai",
    model="gpt-test",
    runtime="openai",
    base_url=None,
    api_key_env="TEST_OPENAI_KEY",
    supports_vision=True,
    price_input=2.0,
    price_output=8.0,
    max_cost_per_turn=None,
    max_steps_per_turn=None,
)
_LITELLM = dataclasses.replace(
    _OPENAI,
    id="p-ds",
    name="deepseek",
    provider="litellm",
    model="deepseek/deepseek-chat",
    api_key_env="TEST_DEEPSEEK_KEY",
)
_ENVIRON = {"TEST_OPENAI_KEY": "sk-openai", "TEST_DEEPSEEK_KEY": "sk-deepseek"}


class Models:
    """Model factory that hands out one `ScriptedModel` per turn and records the key."""

    def __init__(self, *scripts: list[Any]) -> None:
        self.models = [ScriptedModel(script) for script in scripts]
        self.keys: list[str] = []
        self._next = 0

    def __call__(self, profile: ModelProfileValue, api_key: str) -> Model:
        self.keys.append(api_key)
        model = self.models[self._next]
        self._next += 1
        return model

    @property
    def calls(self) -> list[ModelCall]:
        return [call for model in self.models for call in model.calls]


def _noop_record(relpath: str, sha256: str) -> None:
    return None


def _ctx(
    workdir: Path,
    *,
    profile: ModelProfileValue = _OPENAI,
    resume_ref: str | None = None,
    budget: Budget | None = None,
    cancel_token: CancelToken | None = None,
    tools: list[ToolSpec] | None = None,
    allow_web: bool = False,
    user_input: UserInput | None = None,
) -> TurnContext:
    return TurnContext(
        system_prompt="系统提示词",
        user_input=user_input or UserInput(text="你好"),
        tools=tools or [],
        workdir=workdir,
        model_profile=profile,
        resume_ref=resume_ref,
        cancel_token=cancel_token or CancelToken(),
        budget=budget or Budget(),
        write_scope=WriteScope(writable=["topic/**"], tool_managed=["topic/managed.json"]),
        project_id="proj-1",
        stage="topic",
        record_tool_write=_noop_record,
        allow_web=allow_web,
    )


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


def _runtime(data_dir: Path, models: Models, *, history_turns: int = 20) -> OpenAIRuntime:
    return OpenAIRuntime(
        data_dir, model_factory=models, environ=_ENVIRON, history_turns=history_turns
    )


async def _run(runtime: OpenAIRuntime, ctx: TurnContext) -> list[events.AgentEvent]:
    return [event async for event in runtime.run_turn(ctx)]


def _of[T](items: list[events.AgentEvent], kind: type[T]) -> list[T]:
    return [item for item in items if isinstance(item, kind)]


def _end(items: list[events.AgentEvent]) -> events.TurnEnd:
    assert isinstance(items[-1], events.TurnEnd)
    return items[-1]


class _Args(BaseModel):
    text: str


def _echo_spec(handler: Callable[[ToolContext, _Args], ToolResult] | None = None) -> ToolSpec:
    def echo(_ctx: ToolContext, args: _Args) -> ToolResult:
        return ToolResult(text=args.text)

    return ToolSpec("echo", "回显", _Args, {"topic"}, handler or echo)


def _apply_patch_call(call_id: str, kind: str, path: str, diff: str | None) -> dict[str, Any]:
    operation: dict[str, Any] = {"type": kind, "path": path}
    if diff is not None:
        operation["diff"] = diff
    return {"type": "apply_patch_call", "call_id": call_id, "operation": operation}


def _shell_step(call_id: str, commands: list[str]) -> ModelStep:
    """Automatic streaming in ScriptedModel does not cover shell calls; script the events."""
    return _streamed_item(
        ResponseFunctionShellToolCall(
            id=call_id,
            call_id=call_id,
            type="shell_call",
            status="completed",
            action=ShellAction(commands=commands),
        )
    )


def _streamed_item(call: Any) -> ModelStep:
    response = Response(
        id="resp-shell",
        created_at=0,
        model="gpt-test",
        object="response",
        output=[call],
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        status="completed",
    )
    return ModelStep.stream(
        [
            ResponseOutputItemDoneEvent(
                type="response.output_item.done", item=call, output_index=0, sequence_number=0
            ),
            ResponseCompletedEvent(type="response.completed", response=response, sequence_number=1),
        ]
    )


class TestEventConversion:
    async def test_text_tool_call_and_result(self, workdir: Path, data_dir: Path) -> None:
        models = Models(
            [
                [assistant_message("先看看"), function_call("echo", {"text": "hi"}, call_id="c1")],
                [assistant_message("完成")],
            ]
        )
        out = await _run(_runtime(data_dir, models), _ctx(workdir, tools=[_echo_spec()]))

        assert [e.text for e in _of(out, events.TextDelta)] == ["先看看", "完成"]
        assert [e.text for e in _of(out, events.TextBlock)] == ["先看看", "完成"]
        assert _of(out, events.ToolCall) == [
            events.ToolCall(call_id="c1", name="echo", args={"text": "hi"})
        ]
        assert _of(out, events.ToolResult) == [events.ToolResult(call_id="c1", text="hi")]
        end = _end(out)
        assert end.status == "done" and end.error is None
        assert end.resume_ref

    async def test_system_prompt_and_user_text_reach_model(
        self, workdir: Path, data_dir: Path
    ) -> None:
        models = Models([[assistant_message("ok")]])
        await _run(_runtime(data_dir, models), _ctx(workdir))

        (call,) = models.calls
        assert call.system_instructions == "系统提示词"
        assert call.input[-1]["content"] == "你好"
        assert models.keys == ["sk-openai"]

    async def test_user_images_become_input_image_items(
        self, workdir: Path, data_dir: Path
    ) -> None:
        models = Models([[assistant_message("ok")]])
        user_input = UserInput(text="看图", images=[events.ImageData("image/png", "aGk=")])
        await _run(_runtime(data_dir, models), _ctx(workdir, user_input=user_input))

        content = models.calls[0].input[-1]["content"]
        assert content[0] == {"type": "input_text", "text": "看图"}
        assert content[1]["type"] == "input_image"
        assert content[1]["image_url"] == "data:image/png;base64,aGk="

    async def test_business_tool_image_result(self, workdir: Path, data_dir: Path) -> None:
        def render(_ctx: ToolContext, args: _Args) -> ToolResult:
            return ToolResult(text="渲染好了", images=[events.ImageData("image/png", "aW1n")])

        models = Models(
            [[function_call("echo", {"text": "x"}, call_id="c1")], [assistant_message("好")]]
        )
        out = await _run(_runtime(data_dir, models), _ctx(workdir, tools=[_echo_spec(render)]))

        (result,) = _of(out, events.ToolResult)
        assert result.text == "渲染好了"
        assert result.images == [events.ImageData("image/png", "aW1n")]
        # The second model call sees the image as an input_image in the tool output.
        outputs = [
            item for item in models.calls[1].input if item.get("type") == "function_call_output"
        ]
        assert {"type": "input_image", "image_url": "data:image/png;base64,aW1n"} in outputs[0][
            "output"
        ]

    async def test_business_tool_image_result_hidden_when_no_vision(
        self, workdir: Path, data_dir: Path
    ) -> None:
        """R2（deepseek-flash 不支持图片，2026-09-28 冒烟 run2/run3）：
        supports_vision=False 时模型看到的工具输出只剩文本 + 说明，不含图片。"""

        def render(_ctx: ToolContext, args: _Args) -> ToolResult:
            return ToolResult(text="渲染好了", images=[events.ImageData("image/png", "aW1n")])

        models = Models(
            [[function_call("echo", {"text": "x"}, call_id="c1")], [assistant_message("好")]]
        )
        profile = dataclasses.replace(_OPENAI, supports_vision=False)
        out = await _run(
            _runtime(data_dir, models),
            _ctx(workdir, tools=[_echo_spec(render)], profile=profile),
        )

        # Events keep the original ToolResult (images metadata for the canvas/UI).
        (result,) = _of(out, events.ToolResult)
        assert result.images == [events.ImageData("image/png", "aW1n")]
        # But the second model call only sees text, with a note explaining why.
        outputs = [
            item for item in models.calls[1].input if item.get("type") == "function_call_output"
        ]
        assert outputs[0]["output"] == "渲染好了\n（模型不支持图片，已省略图片内容）"

    async def test_business_tool_bad_args_is_error_result(
        self, workdir: Path, data_dir: Path
    ) -> None:
        models = Models(
            [[function_call("echo", {"wrong": 1}, call_id="c1")], [assistant_message("好")]]
        )
        out = await _run(_runtime(data_dir, models), _ctx(workdir, tools=[_echo_spec()]))

        (result,) = _of(out, events.ToolResult)
        assert result.is_error
        assert _end(out).status == "done"

    async def test_business_tool_context(self, workdir: Path, data_dir: Path) -> None:
        seen: list[ToolContext] = []

        def capture(ctx: ToolContext, args: _Args) -> ToolResult:
            seen.append(ctx)
            return ToolResult(text="ok")

        models = Models(
            [[function_call("echo", {"text": "x"}, call_id="c1")], [assistant_message("好")]]
        )
        await _run(_runtime(data_dir, models), _ctx(workdir, tools=[_echo_spec(capture)]))

        assert seen[0].project_id == "proj-1"
        assert seen[0].stage == "topic"
        assert seen[0].workdir == workdir

    async def test_model_error_ends_failed(self, workdir: Path, data_dir: Path) -> None:
        models = Models([RuntimeError("upstream exploded")])
        out = await _run(_runtime(data_dir, models), _ctx(workdir))

        end = _end(out)
        assert end.status == "failed"
        assert end.error is not None and "upstream exploded" in end.error


class TestNativeTools:
    async def test_openai_tool_surface(self, workdir: Path, data_dir: Path) -> None:
        models = Models([[assistant_message("ok")]])
        await _run(_runtime(data_dir, models), _ctx(workdir, tools=[_echo_spec()]))

        tools = models.calls[0].tools
        assert any(isinstance(tool, ApplyPatchTool) for tool in tools)
        assert any(isinstance(tool, ShellTool) for tool in tools)
        assert not any(isinstance(tool, WebSearchTool) for tool in tools)
        names = {tool.name for tool in tools if isinstance(tool, FunctionTool)}
        assert names == {"echo"}

    async def test_official_base_url_keeps_shell(self, workdir: Path, data_dir: Path) -> None:
        profile = dataclasses.replace(_OPENAI, base_url="https://api.openai.com/v1")
        models = Models([[assistant_message("ok")]])
        await _run(_runtime(data_dir, models), _ctx(workdir, profile=profile))

        assert any(isinstance(tool, ShellTool) for tool in models.calls[0].tools)

    async def test_gateway_base_url_drops_shell_adds_read_tools(
        self, workdir: Path, data_dir: Path
    ) -> None:
        """OpenRouter has no client-side shell (only hosted sandboxes that cannot see
        the workspace), so a non-OpenAI base_url gets apply_patch + read-only fallback
        tools instead of ShellTool (F2, docs/references/openai-agents-sdk.md)."""
        profile = dataclasses.replace(_OPENAI, base_url="https://openrouter.ai/api/v1")
        models = Models([[assistant_message("ok")]])
        await _run(
            _runtime(data_dir, models),
            _ctx(workdir, profile=profile, tools=[_echo_spec()], allow_web=True),
        )

        tools = models.calls[0].tools
        assert not any(isinstance(tool, ShellTool) for tool in tools)
        assert any(isinstance(tool, ApplyPatchTool) for tool in tools)
        assert any(isinstance(tool, WebSearchTool) for tool in tools)
        names = {tool.name for tool in tools if isinstance(tool, FunctionTool)}
        assert names == {"echo", "list_files", "read_file"}

    @pytest.mark.parametrize(
        ("profile", "gateway"),
        [
            (_OPENAI, False),
            (dataclasses.replace(_OPENAI, base_url="https://api.openai.com/v1"), False),
            (dataclasses.replace(_OPENAI, base_url="https://openrouter.ai/api/v1"), True),
            (dataclasses.replace(_LITELLM, base_url="https://openrouter.ai/api/v1"), False),
        ],
    )
    async def test_stateless_settings_only_on_openai_gateways(
        self, workdir: Path, data_dir: Path, profile: ModelProfileValue, gateway: bool
    ) -> None:
        """OpenRouter's Responses API stores nothing, so replayed reasoning items must
        carry their encrypted content (F2 review)."""
        models = Models([[assistant_message("ok")]])
        await _run(_runtime(data_dir, models), _ctx(workdir, profile=profile))

        settings = models.calls[0].model_settings
        assert settings.include_usage is True
        if gateway:
            assert settings.store is False
            assert settings.response_include == ["reasoning.encrypted_content"]
        else:
            assert settings.store is None
            assert settings.response_include is None

    def test_native_shell_supported(self) -> None:
        assert native_shell_supported(_OPENAI)
        for url in ("https://api.openai.com/v1", "https://API.openai.com/v1/"):
            assert native_shell_supported(dataclasses.replace(_OPENAI, base_url=url))
        for url in (
            "https://openrouter.ai/api/v1",
            "https://api.openai.com.evil.example/v1",
            "http://127.0.0.1:4000/v1",
        ):
            assert not native_shell_supported(dataclasses.replace(_OPENAI, base_url=url))

    async def test_web_search_only_when_allowed(self, workdir: Path, data_dir: Path) -> None:
        models = Models([[assistant_message("ok")]])
        await _run(_runtime(data_dir, models), _ctx(workdir, allow_web=True))

        assert any(isinstance(tool, WebSearchTool) for tool in models.calls[0].tools)

    async def test_apply_patch_writes_through_workspace(
        self, workdir: Path, data_dir: Path
    ) -> None:
        models = Models(
            [
                [
                    _apply_patch_call("p1", "create_file", "topic/a.md", "+hello"),
                    _apply_patch_call("p2", "create_file", "style/STYLE.md", "+hack"),
                ],
                [assistant_message("好")],
            ]
        )
        out = await _run(_runtime(data_dir, models), _ctx(workdir))

        assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "hello"
        assert not (workdir / "style" / "STYLE.md").exists()
        calls = _of(out, events.ToolCall)
        assert [call.name for call in calls] == ["apply_patch", "apply_patch"]
        # The runner reads args["path"] to publish a precise workspace_changed.
        assert calls[0].args["path"] == "topic/a.md"
        assert calls[0].args["type"] == "create_file"
        ok, rejected = _of(out, events.ToolResult)
        assert not ok.is_error
        assert rejected.is_error and "style/STYLE.md" in rejected.text
        assert "apply_patch" in events.FILE_TOOL_NAMES

    async def test_shell_runs_in_workdir(self, workdir: Path, data_dir: Path) -> None:
        models = Models([_shell_step("s1", ["pwd"]), [assistant_message("好")]])
        out = await _run(_runtime(data_dir, models), _ctx(workdir))

        (call,) = _of(out, events.ToolCall)
        assert call.name == "shell" and call.args == {"commands": ["pwd"]}
        assert call.name in events.FILE_TOOL_NAMES
        (result,) = _of(out, events.ToolResult)
        assert str(workdir.resolve()) in result.text
        assert not result.is_error

    async def test_failing_shell_command_is_error_result(
        self, workdir: Path, data_dir: Path
    ) -> None:
        models = Models([_shell_step("s1", ["exit 3"]), [assistant_message("好")]])
        out = await _run(_runtime(data_dir, models), _ctx(workdir))

        (result,) = _of(out, events.ToolResult)
        assert result.is_error


class TestLitellmPath:
    async def test_fallback_tools_and_no_shell_or_web(self, workdir: Path, data_dir: Path) -> None:
        models = Models([[assistant_message("ok")]])
        await _run(
            _runtime(data_dir, models),
            _ctx(workdir, profile=_LITELLM, tools=[_echo_spec()], allow_web=True),
        )

        tools = models.calls[0].tools
        assert all(isinstance(tool, FunctionTool) for tool in tools)
        assert {tool.name for tool in tools} == {
            "echo",
            "list_files",
            "read_file",
            "write_file",
            "edit_file",
        }
        assert models.keys == ["sk-deepseek"]

    async def test_fallback_write_goes_through_scope(self, workdir: Path, data_dir: Path) -> None:
        models = Models(
            [
                [
                    function_call(
                        "write_file", {"path": "topic/a.md", "content": "hi"}, call_id="w1"
                    ),
                    function_call(
                        "write_file", {"path": "style/x.md", "content": "no"}, call_id="w2"
                    ),
                ],
                [assistant_message("好")],
            ]
        )
        out = await _run(_runtime(data_dir, models), _ctx(workdir, profile=_LITELLM))

        assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "hi"
        assert not (workdir / "style" / "x.md").exists()
        ok, rejected = _of(out, events.ToolResult)
        assert not ok.is_error and rejected.is_error
        assert {"write_file", "edit_file"} <= events.FILE_TOOL_NAMES


class TestBuildModel:
    def test_openai_uses_responses_model_with_explicit_client(self) -> None:
        profile = dataclasses.replace(_OPENAI, base_url="https://proxy.example/v1")
        assert isinstance(build_model(profile, "sk-x"), OpenAIResponsesModel)

        client = openai_client(profile, "sk-x")
        assert client.api_key == "sk-x"
        assert str(client.base_url).startswith("https://proxy.example/v1")

    def test_litellm_passes_key_and_base_url_explicitly(self) -> None:
        profile = dataclasses.replace(_LITELLM, base_url="https://api.deepseek.example")
        model = build_model(profile, "sk-ds")

        assert isinstance(model, LitellmModel)
        assert model.model == "deepseek/deepseek-chat"
        assert model.api_key == "sk-ds"
        assert model.base_url == "https://api.deepseek.example"

    async def test_unknown_provider_fails_turn(self, workdir: Path, data_dir: Path) -> None:
        profile = dataclasses.replace(_OPENAI, provider="mystery")
        runtime = OpenAIRuntime(data_dir, environ=_ENVIRON)
        out = await _run(runtime, _ctx(workdir, profile=profile))

        end = _end(out)
        assert end.status == "failed" and end.error is not None and "mystery" in end.error


class TestAuth:
    async def test_missing_key_fails_without_calling_model(
        self, workdir: Path, data_dir: Path
    ) -> None:
        models = Models([[assistant_message("ok")]])
        runtime = OpenAIRuntime(data_dir, model_factory=models, environ={})
        out = await _run(runtime, _ctx(workdir))

        end = _end(out)
        assert end.status == "failed"
        assert end.error is not None and "TEST_OPENAI_KEY" in end.error
        assert models.keys == []

    async def test_profile_without_key_env_fails(self, workdir: Path, data_dir: Path) -> None:
        models = Models([[assistant_message("ok")]])
        profile = dataclasses.replace(_OPENAI, api_key_env=None)
        out = await _run(_runtime(data_dir, models), _ctx(workdir, profile=profile))

        assert _end(out).status == "failed"
        assert models.keys == []

    async def test_key_is_not_written_to_process_environment(
        self, workdir: Path, data_dir: Path
    ) -> None:
        models = Models([[assistant_message("ok")]])
        await _run(_runtime(data_dir, models), _ctx(workdir))
        assert "TEST_OPENAI_KEY" not in os.environ


class TestUsage:
    def test_turn_cost_is_per_million_tokens(self) -> None:
        assert turn_cost(_OPENAI, 1000, 500) == pytest.approx(0.006)

    def test_turn_cost_without_prices_is_zero(self) -> None:
        profile = dataclasses.replace(_OPENAI, price_input=None, price_output=None)
        assert turn_cost(profile, 1000, 500) == 0.0

    async def test_usage_event_per_model_call(self, workdir: Path, data_dir: Path) -> None:
        usage = Usage(requests=1, input_tokens=1000, output_tokens=500, total_tokens=1500)
        models = Models(
            [
                ModelStep(output=[function_call("echo", {"text": "x"}, call_id="c1")], usage=usage),
                ModelStep(output=[assistant_message("好")], usage=usage),
            ]
        )
        out = await _run(_runtime(data_dir, models), _ctx(workdir, tools=[_echo_spec()]))

        usages = _of(out, events.Usage)
        assert len(usages) == 2
        first = usages[0]
        assert (first.input_tokens, first.output_tokens, first.auth) == (1000, 500, "api_key")
        assert first.cost_usd == pytest.approx(0.006)
        # The first call's usage arrives before the tool call it produced finishes the turn.
        assert out.index(usages[0]) < out.index(_of(out, events.ToolResult)[0])

    async def test_cost_budget_without_prices_fails(self, workdir: Path, data_dir: Path) -> None:
        models = Models([[assistant_message("ok")]])
        profile = dataclasses.replace(_OPENAI, price_output=None)
        out = await _run(
            _runtime(data_dir, models),
            _ctx(workdir, profile=profile, budget=Budget(max_cost_usd=1.0)),
        )

        end = _end(out)
        assert end.status == "failed" and end.error is not None and "单价" in end.error
        assert models.keys == []


class TestCancel:
    async def test_cancel_token_stops_the_run(self, workdir: Path, data_dir: Path) -> None:
        gate = asyncio.Event()

        async def hang(call: ModelCall) -> list[Any]:
            await gate.wait()
            return [assistant_message("太晚了")]

        models = Models([ModelStep.respond(hang)])
        token = CancelToken()
        runtime = _runtime(data_dir, models)

        async def cancel_soon() -> None:
            await asyncio.sleep(0.05)
            token.cancel()

        canceller = asyncio.create_task(cancel_soon())
        out = await asyncio.wait_for(_run(runtime, _ctx(workdir, cancel_token=token)), 5)
        await canceller

        end = _end(out)
        assert end.status == "cancelled"
        assert end.resume_ref
        assert not _of(out, events.TextBlock)

    async def test_already_cancelled_token(self, workdir: Path, data_dir: Path) -> None:
        models = Models([[assistant_message("ok")]])
        token = CancelToken()
        token.cancel()
        out = await asyncio.wait_for(
            _run(_runtime(data_dir, models), _ctx(workdir, cancel_token=token)), 5
        )
        assert _end(out).status == "cancelled"


class TestMaxTurns:
    """TD-18: the runner enforces the step budget; the SDK's `max_turns` is only a
    loose backstop derived from it (plan decision: `max_steps * 2 + 2`)."""

    def test_unlimited_steps_use_default_cap(self) -> None:
        assert max_turns(Budget()) == MAX_TURNS

    def test_derived_from_step_budget(self) -> None:
        assert max_turns(Budget(max_steps=5)) == 12

    async def test_backstop_applies_to_the_run(self, workdir: Path, data_dir: Path) -> None:
        models = Models(
            [[function_call("echo", {"text": str(i)}, call_id=f"c{i}")] for i in range(3)]
            + [[assistant_message("完成")]]
        )
        out = await _run(
            _runtime(data_dir, models),
            _ctx(workdir, tools=[_echo_spec()], budget=Budget(max_steps=0)),
        )

        end = _end(out)
        assert end.status == "failed"
        assert end.error is not None and "（2）" in end.error


def _user_texts(call: ModelCall) -> list[str]:
    return [
        item["content"]
        for item in call.input
        if isinstance(item, dict) and item.get("role") == "user"
    ]


class TestSession:
    async def test_resume_ref_continues_history(self, workdir: Path, data_dir: Path) -> None:
        models = Models([[assistant_message("一")]], [[assistant_message("二")]])
        runtime = _runtime(data_dir, models)

        first = await _run(runtime, _ctx(workdir, user_input=UserInput(text="第一轮")))
        ref = _end(first).resume_ref
        second = await _run(
            runtime, _ctx(workdir, resume_ref=ref, user_input=UserInput(text="第二轮"))
        )

        assert _end(second).resume_ref == ref
        assert _user_texts(models.calls[1]) == ["第一轮", "第二轮"]
        assert (data_dir / "openai_sessions.db").is_file()

    async def test_only_recent_turns_are_sent(self, workdir: Path, data_dir: Path) -> None:
        models = Models(
            [[assistant_message("一")]], [[assistant_message("二")]], [[assistant_message("三")]]
        )
        runtime = _runtime(data_dir, models, history_turns=1)

        ref = _end(await _run(runtime, _ctx(workdir, user_input=UserInput(text="1")))).resume_ref
        await _run(runtime, _ctx(workdir, resume_ref=ref, user_input=UserInput(text="2")))
        await _run(runtime, _ctx(workdir, resume_ref=ref, user_input=UserInput(text="3")))

        assert _user_texts(models.calls[2]) == ["2", "3"]


class TestShellExecutor:
    def _request(self, commands: list[str], timeout_ms: int | None = None) -> ShellCommandRequest:
        data = ShellCallData(
            call_id="s1", action=ShellActionRequest(commands=commands, timeout_ms=timeout_ms)
        )
        return ShellCommandRequest(ctx_wrapper=RunContextWrapper(context=None), data=data)

    async def test_uses_injected_environ_without_secrets(
        self, workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STUDIO_ONLY_IN_PROCESS_ENV", "leak")
        environ = {"PATH": os.environ["PATH"], "FOO": "bar", "MY_TOKEN": "secret"}
        executor = LocalShellExecutor(workdir, set(), environ=environ)

        result = await executor(
            self._request(['echo "$FOO|$MY_TOKEN|$STUDIO_ONLY_IN_PROCESS_ENV"'])
        )

        assert result.output[0].stdout.strip() == "bar||"

    async def test_runs_in_workdir_and_captures_output(self, workdir: Path) -> None:
        failed: set[str] = set()
        result = await LocalShellExecutor(workdir, failed)(self._request(["pwd", "echo err >&2"]))

        first, second = result.output
        assert first.stdout.strip() == str(workdir.resolve())
        assert first.exit_code == 0
        assert second.stderr.strip() == "err"
        assert failed == set()

    async def test_timeout_kills_command(self, workdir: Path) -> None:
        failed: set[str] = set()
        executor = LocalShellExecutor(workdir, failed)

        result = await asyncio.wait_for(executor(self._request(["sleep 5"], timeout_ms=200)), 3)

        (output,) = result.output
        assert output.status == "timeout"
        assert failed == {"s1"}

    async def test_nonzero_exit_marks_failed(self, workdir: Path) -> None:
        failed: set[str] = set()
        result = await LocalShellExecutor(workdir, failed)(self._request(["exit 2"]))

        assert result.output[0].exit_code == 2
        assert failed == {"s1"}

    async def test_output_is_truncated(self, workdir: Path) -> None:
        executor = LocalShellExecutor(workdir, set(), max_output_chars=100)
        result = await executor(self._request(["yes x | head -c 5000"]))

        assert len(result.output[0].stdout) < 200
        assert "截断" in result.output[0].stdout

    async def test_secrets_are_not_inherited(
        self, workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SOME_API_KEY", "leak")
        monkeypatch.setenv("HARMLESS_VALUE", "ok")
        executor = LocalShellExecutor(workdir, set())

        result = await executor(self._request(['echo "[$SOME_API_KEY][$HARMLESS_VALUE]"']))

        assert result.output[0].stdout.strip() == "[][ok]"


def test_register_openai(tmp_path: Path) -> None:
    factory = RuntimeFactory()
    register_openai(factory, Settings(data_dir=tmp_path / "data"))

    assert factory.has("openai")
    assert isinstance(factory.create("openai"), OpenAIRuntime)


def test_settings_history_turns_default() -> None:
    assert Settings().openai_history_turns == 20


async def _group_gone(pgid: int) -> bool:
    for _ in range(100):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True  # pid reused by a process we do not own
        await asyncio.sleep(0.02)
    return False


class TestShellProcessGroup:
    def _request(self, commands: list[str], timeout_ms: int | None = None) -> ShellCommandRequest:
        data = ShellCallData(
            call_id="s1", action=ShellActionRequest(commands=commands, timeout_ms=timeout_ms)
        )
        return ShellCommandRequest(ctx_wrapper=RunContextWrapper(context=None), data=data)

    @pytest.mark.parametrize(
        "background",
        [
            "nohup sh -c 'sleep 0.5; touch marker' > /dev/null 2>&1 &",
            "(sleep 0.5; touch marker) &",  # still holds the stdout pipe
        ],
    )
    async def test_background_processes_die_with_the_command(
        self, workdir: Path, background: str
    ) -> None:
        executor = LocalShellExecutor(workdir, set())

        result = await asyncio.wait_for(executor(self._request([f"echo $$; {background}"])), 3)

        pgid = int(result.output[0].stdout.split()[0])
        assert await _group_gone(pgid)
        await asyncio.sleep(0.8)
        assert not (workdir / "marker").exists()

    async def test_output_flood_is_capped_and_killed(self, workdir: Path) -> None:
        failed: set[str] = set()
        executor = LocalShellExecutor(workdir, failed, max_output_chars=1000)

        result = await asyncio.wait_for(executor(self._request(["yes"], timeout_ms=10_000)), 5)

        (output,) = result.output
        assert output.status == "completed"
        assert len(output.stdout) < 1200
        assert "终止" in output.stderr
        assert failed == {"s1"}

    async def test_cancel_while_shell_runs(self, workdir: Path, data_dir: Path) -> None:
        models = Models([_shell_step("s1", ["echo $$ > pgid; sleep 30"])])
        token = CancelToken()
        runtime = _runtime(data_dir, models)

        async def cancel_when_started() -> None:
            while not (workdir / "pgid").exists() or not (workdir / "pgid").read_text():
                await asyncio.sleep(0.02)
            token.cancel()

        canceller = asyncio.create_task(cancel_when_started())
        out = await asyncio.wait_for(_run(runtime, _ctx(workdir, cancel_token=token)), 5)
        await canceller

        assert _end(out).status == "cancelled"
        pgid = int((workdir / "pgid").read_text())
        assert await _group_gone(pgid)


class TestReviewFixes:
    async def test_web_search_call_gets_synthesized_result(
        self, workdir: Path, data_dir: Path
    ) -> None:
        search = ResponseFunctionWebSearch(
            id="ws1",
            type="web_search_call",
            status="completed",
            action=ActionSearch(type="search", query="manim"),
        )
        models = Models([_streamed_item(search), [assistant_message("好")]])
        out = await _run(_runtime(data_dir, models), _ctx(workdir, allow_web=True))

        assert _of(out, events.ToolCall) == [
            events.ToolCall(call_id="ws1", name="web_search", args={"query": "manim"})
        ]
        (result,) = _of(out, events.ToolResult)
        assert result.call_id == "ws1" and not result.is_error
        assert "completed" in result.text

    async def test_apply_patch_args_are_normalised_with_move_to(
        self, workdir: Path, data_dir: Path
    ) -> None:
        (workdir / "topic").mkdir()
        (workdir / "topic" / "a.md").write_text("a\n", encoding="utf-8")
        call = _apply_patch_call("p1", "update_file", str(workdir / "topic" / "a.md"), "@@\n-a\n+b")
        call["operation"]["move_to"] = "./topic//b.md"
        models = Models([[call], [assistant_message("好")]])

        out = await _run(_runtime(data_dir, models), _ctx(workdir))

        (tool_call,) = _of(out, events.ToolCall)
        assert tool_call.args["path"] == "topic/a.md"
        assert tool_call.args["move_to"] == "topic/b.md"
        assert (workdir / "topic" / "b.md").read_text(encoding="utf-8") == "b\n"

    def test_non_strict_fallback_logs_warning(
        self, workdir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        class Open(BaseModel):
            data: dict[str, Any]

        def handler(_ctx: ToolContext, args: Open) -> ToolResult:
            return ToolResult(text="ok")

        spec = ToolSpec("open", "开放参数", Open, {"topic"}, handler)
        tool_ctx = ToolContext("p", "topic", workdir, _noop_record)
        with caplog.at_level(logging.WARNING, logger="studio.agent.openai_runtime"):
            tool = build_function_tool(spec, tool_ctx, {})

        assert tool.strict_json_schema is False
        assert any("strict" in record.getMessage() for record in caplog.records)

    async def test_unpriced_usage_is_flagged(self, workdir: Path, data_dir: Path) -> None:
        usage = Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15)
        models = Models([ModelStep(output=[assistant_message("好")], usage=usage)])
        profile = dataclasses.replace(_OPENAI, price_input=None, price_output=None)

        out = await _run(_runtime(data_dir, models), _ctx(workdir, profile=profile))

        (reported,) = _of(out, events.Usage)
        assert reported.priced is False and reported.cost_usd == 0.0

    async def test_priced_usage_is_flagged_priced(self, workdir: Path, data_dir: Path) -> None:
        models = Models([[assistant_message("好")]])
        out = await _run(_runtime(data_dir, models), _ctx(workdir))
        assert all(u.priced for u in _of(out, events.Usage))
