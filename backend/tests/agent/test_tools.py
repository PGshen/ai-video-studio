from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from studio.agent.events import ImageData
from studio.agent.tools import ToolContext, ToolResult, ToolSpec, invoke_tool


class _EchoArgs(BaseModel):
    text: str


def _echo_handler(ctx: ToolContext, args: _EchoArgs) -> ToolResult:
    return ToolResult(text=f"echo: {args.text}")


def _raising_handler(ctx: ToolContext, args: _EchoArgs) -> ToolResult:
    raise RuntimeError("boom")


async def _async_handler(ctx: ToolContext, args: _EchoArgs) -> ToolResult:
    return ToolResult(text=f"async echo: {args.text}")


def _recording_handler(ctx: ToolContext, args: _EchoArgs) -> ToolResult:
    ctx.record_tool_write("narrative/timing.json", "deadbeef")
    return ToolResult(text="recorded")


@pytest.fixture
def ctx(workdir: Path) -> ToolContext:
    records: list[tuple[str, str]] = []
    return ToolContext(
        project_id="proj-1",
        stage="narrative",
        workdir=workdir,
        record_tool_write=lambda relpath, sha256: records.append((relpath, sha256)),
    )


class TestToolResult:
    def test_defaults(self) -> None:
        result = ToolResult(text="ok")
        assert result.images == []
        assert result.is_error is False

    def test_with_images(self) -> None:
        image = ImageData(media_type="image/png", data_base64="AA==")
        result = ToolResult(text="ok", images=[image], is_error=False)
        assert result.images == [image]


class TestInvokeTool:
    async def test_valid_args_returns_handler_result(self, ctx: ToolContext) -> None:
        spec = ToolSpec(
            name="echo",
            description="echo back",
            input_model=_EchoArgs,
            stages={"narrative"},
            handler=_echo_handler,
        )

        result = await invoke_tool(spec, ctx, {"text": "hi"})

        assert result == ToolResult(text="echo: hi")

    async def test_async_handler_is_awaited(self, ctx: ToolContext) -> None:
        spec = ToolSpec(
            name="echo",
            description="echo back",
            input_model=_EchoArgs,
            stages={"narrative"},
            handler=_async_handler,
        )

        result = await invoke_tool(spec, ctx, {"text": "hi"})

        assert result == ToolResult(text="async echo: hi")

    async def test_invalid_args_become_error_result(self, ctx: ToolContext) -> None:
        spec = ToolSpec(
            name="echo",
            description="echo back",
            input_model=_EchoArgs,
            stages={"narrative"},
            handler=_echo_handler,
        )

        result = await invoke_tool(spec, ctx, {"wrong_field": "hi"})

        assert result.is_error is True

    async def test_handler_exception_becomes_error_result(self, ctx: ToolContext) -> None:
        spec = ToolSpec(
            name="boom",
            description="raises",
            input_model=_EchoArgs,
            stages={"narrative"},
            handler=_raising_handler,
        )

        result = await invoke_tool(spec, ctx, {"text": "hi"})

        assert result.is_error is True
        assert "boom" in result.text

    async def test_handler_can_record_tool_write_via_context(self, ctx: ToolContext) -> None:
        spec = ToolSpec(
            name="record",
            description="records a tool write",
            input_model=_EchoArgs,
            stages={"narrative"},
            handler=_recording_handler,
        )

        result = await invoke_tool(spec, ctx, {"text": "hi"})

        assert result == ToolResult(text="recorded")


def test_require_project_returns_id(ctx: ToolContext) -> None:
    assert ctx.require_project() == "proj-1"


def test_require_project_raises_without_project(workdir: Path) -> None:
    no_project = ToolContext(
        project_id=None,
        stage="brainstorm",
        workdir=workdir,
        record_tool_write=lambda *_: None,
        session_id="s1",
    )
    with pytest.raises(RuntimeError, match="项目"):
        no_project.require_project()


async def test_invoke_tool_turns_missing_project_into_error_result(workdir: Path) -> None:
    def needs_project(ctx: ToolContext, args: _EchoArgs) -> ToolResult:
        ctx.require_project()
        return ToolResult(text="unreachable")

    spec = ToolSpec(
        name="needs_project",
        description="d",
        input_model=_EchoArgs,
        stages={"brainstorm"},
        handler=needs_project,
    )
    no_project = ToolContext(
        project_id=None, stage="brainstorm", workdir=workdir, record_tool_write=lambda *_: None
    )
    result = await invoke_tool(spec, no_project, {"text": "x"})
    assert result.is_error
    assert "项目" in result.text
