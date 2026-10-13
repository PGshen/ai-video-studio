"""`codex_mcp.TurnToolServer`：本轮业务工具的 HTTP MCP 端点（codex-runtime T2）。

不起 codex，直接用 `mcp` 客户端连本轮服务。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import BaseModel

from studio.agent.codex_mcp import TOKEN_ENV, CodexMcpConfig, TurnToolServer
from studio.agent.events import ImageData
from studio.agent.tools import ToolContext, ToolHandler, ToolResult, ToolSpec


class _EchoArgs(BaseModel):
    text: str


def _spec(name: str, handler: ToolHandler) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"{name} tool",
        input_model=_EchoArgs,
        stages={"narrative"},
        handler=handler,
    )


def _echo(ctx: ToolContext, args: _EchoArgs) -> ToolResult:
    ctx.record_tool_write("narrative/timing.json", "beef")
    return ToolResult(text=f"echo: {args.text}")


def _picture(ctx: ToolContext, args: _EchoArgs) -> ToolResult:
    return ToolResult(text="a swatch", images=[ImageData("image/png", "AAAA")])


def _boom(ctx: ToolContext, args: _EchoArgs) -> ToolResult:
    raise RuntimeError("boom")


@pytest.fixture
def records() -> list[tuple[str, str]]:
    return []


@pytest.fixture
def tool_ctx(tmp_path: Path, records: list[tuple[str, str]]) -> ToolContext:
    return ToolContext(
        project_id="proj-1",
        stage="narrative",
        workdir=tmp_path,
        record_tool_write=lambda relpath, sha: records.append((relpath, sha)),
    )


TOOLS = [_spec("echo", _echo), _spec("picture", _picture), _spec("boom", _boom)]


@asynccontextmanager
async def _client(config: CodexMcpConfig, token: str | None = None) -> AsyncIterator[ClientSession]:
    assert config.url is not None
    headers = {"Authorization": f"Bearer {token or config.env[TOKEN_ENV]}"}
    async with (
        httpx.AsyncClient(headers=headers) as http,
        streamable_http_client(config.url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


def _text(result: CallToolResult) -> str:
    first = result.content[0]
    assert isinstance(first, TextContent)
    return first.text


def _overrides(config: CodexMcpConfig) -> dict[str, str]:
    args = config.args()
    assert args[::2] == ["-c"] * (len(args) // 2)
    return dict(item.split("=", 1) for item in args[1::2])


async def test_config_points_codex_at_the_server(tool_ctx: ToolContext) -> None:
    async with TurnToolServer(TOOLS, tool_ctx) as config:
        overrides = _overrides(config)
        assert config.url is not None and config.url.startswith("http://127.0.0.1:")
        assert overrides["mcp_servers.studio.url"] == f'"{config.url}"'
        assert overrides["mcp_servers.studio.bearer_token_env_var"] == f'"{TOKEN_ENV}"'
        assert overrides["mcp_servers.studio.default_tools_approval_mode"] == '"approve"'
        assert overrides["mcp_servers.studio.enabled_tools"] == '["echo", "picture", "boom"]'
        # A server that fails to start must fail the turn, not silently drop the tools (r2b).
        assert overrides["mcp_servers.studio.required"] == "true"
        assert int(overrides["mcp_servers.studio.tool_timeout_sec"]) >= 600
        assert len(config.env[TOKEN_ENV]) >= 32


async def test_no_tools_means_no_server(tool_ctx: ToolContext) -> None:
    async with TurnToolServer([], tool_ctx) as config:
        assert config.url is None
        assert config.args() == []
        assert config.env == {}


async def test_lists_only_this_turns_tools(tool_ctx: ToolContext) -> None:
    async with TurnToolServer(TOOLS[:2], tool_ctx) as config, _client(config) as session:
        listed = await session.list_tools()
    assert [tool.name for tool in listed.tools] == ["echo", "picture"]
    assert listed.tools[0].description == "echo tool"
    assert listed.tools[0].inputSchema["properties"]["text"]["type"] == "string"


async def test_call_goes_through_invoke_tool(
    tool_ctx: ToolContext, records: list[tuple[str, str]]
) -> None:
    async with TurnToolServer(TOOLS, tool_ctx) as config, _client(config) as session:
        ok = await session.call_tool("echo", {"text": "hi"})
        picture = await session.call_tool("picture", {"text": "x"})
        bad_args = await session.call_tool("echo", {"wrong": 1})
        failing = await session.call_tool("boom", {"text": "x"})
    assert not ok.isError and _text(ok) == "echo: hi"
    assert records == [("narrative/timing.json", "beef")]
    assert [c.type for c in picture.content] == ["text", "image"]
    image = picture.content[1]
    assert isinstance(image, ImageContent)
    assert image.data == "AAAA" and image.mimeType == "image/png"
    assert bad_args.isError and "参数不合法" in _text(bad_args)
    assert failing.isError and "boom" in _text(failing)


async def test_rejects_wrong_or_missing_token(tool_ctx: ToolContext) -> None:
    async with TurnToolServer(TOOLS, tool_ctx) as config:
        assert config.url is not None
        async with httpx.AsyncClient() as http:
            missing = await http.post(config.url, json={})
            wrong = await http.post(config.url, json={}, headers={"Authorization": "Bearer nope"})
    assert missing.status_code == 401
    assert wrong.status_code == 401


async def test_server_is_gone_after_exit(tool_ctx: ToolContext) -> None:
    async with TurnToolServer(TOOLS, tool_ctx) as config:
        url = config.url
    assert url is not None
    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.ConnectError):
            await http.post(url, json={})


async def test_concurrent_turns_do_not_share_tokens(tool_ctx: ToolContext) -> None:
    async with TurnToolServer(TOOLS, tool_ctx) as first, TurnToolServer(TOOLS, tool_ctx) as second:
        assert first.url != second.url
        assert first.env[TOKEN_ENV] != second.env[TOKEN_ENV]
        assert second.url is not None
        async with httpx.AsyncClient() as http:
            crossed = await http.post(
                second.url, json={}, headers={"Authorization": f"Bearer {first.env[TOKEN_ENV]}"}
            )
    assert crossed.status_code == 401
