"""本轮业务工具的 HTTP MCP 端点，供 codex 调用（ADR 0030「业务工具」，codex-runtime T2）。

每轮在后端进程里起一个只监听 `127.0.0.1`、随机端口的 streamable HTTP MCP 服务，随机令牌经
子进程环境变量 `TOKEN_ENV` 交给 codex（`bearer_token_env_var`），本轮结束即关闭。工具调用在
后端进程内执行，handler 直接拿到本轮 `ToolContext`，统一走 `invoke_tool`（与 Claude 的进程内
MCP 一致）。选它而不是 stdio 桥接进程的实测见 docs/references/codex.md「业务工具」。

codex 侧配置：`default_tools_approval_mode="approve"`（否则 exec 模式下调用直接失败）、
`enabled_tools` 只开放本轮工具、`required=true`（服务连不上时 codex 立即失败，而不是悄悄
去掉这些工具继续跑，实测 `r2b`）。
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import secrets
import socket
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from studio.agent.tools import ToolContext, ToolSpec, invoke_tool

SERVER_NAME = "studio"
TOKEN_ENV = "STUDIO_CODEX_MCP_TOKEN"
"""codex 子进程里放本轮令牌的环境变量名（由运行时在清理继承环境之后加入）。"""
TOOL_TIMEOUT_S = 900
"""单次工具调用的上限：渲染预览、配乐合成等工具要跑几分钟（codex 默认值偏短）。"""
_PATH = "/mcp"
_PREFIX = f"mcp_servers.{SERVER_NAME}."


def _toml_string(value: str) -> str:
    # JSON string escaping is valid TOML basic-string syntax.
    return json.dumps(value)


@dataclass(frozen=True, slots=True)
class CodexMcpConfig:
    """codex 连接本轮服务需要的 `-c` 覆盖项和环境变量；没有工具时都为空。"""

    url: str | None = None
    overrides: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)

    def args(self) -> list[str]:
        out: list[str] = []
        for key, value in self.overrides.items():
            out += ["-c", f"{key}={value}"]
        return out


def _build_server(tools: Sequence[ToolSpec], tool_ctx: ToolContext) -> Server[Any, Any]:
    by_name = {spec.name: spec for spec in tools}
    server: Server[Any, Any] = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.input_model.model_json_schema(),
            )
            for spec in tools
        ]

    # Arguments are validated once, by `invoke_tool` (pydantic), like the other runtimes.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        spec = by_name.get(name)
        if spec is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"未知工具：{name}")], isError=True
            )
        result = await invoke_tool(spec, tool_ctx, arguments)
        content: list[types.TextContent | types.ImageContent] = [
            types.TextContent(type="text", text=result.text)
        ]
        content += [
            types.ImageContent(type="image", data=image.data_base64, mimeType=image.media_type)
            for image in result.images
        ]
        return types.CallToolResult(content=list(content), isError=result.is_error)

    return server


class _BearerGate:
    """只放行带本轮令牌的请求；其余一律 401。"""

    def __init__(self, inner: StreamableHTTPSessionManager, token: str) -> None:
        self._inner = inner
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return
        auth = dict(scope["headers"]).get(b"authorization", b"")
        if not hmac.compare_digest(auth, self._expected):
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
        await self._inner.handle_request(scope, receive, send)


class TurnToolServer:
    """`async with TurnToolServer(tools, tool_ctx) as config:` —— 本轮的 MCP 端点。"""

    def __init__(self, tools: Sequence[ToolSpec], tool_ctx: ToolContext) -> None:
        self._tools = list(tools)
        self._tool_ctx = tool_ctx
        self._stack = contextlib.AsyncExitStack()

    async def __aenter__(self) -> CodexMcpConfig:
        if not self._tools:
            return CodexMcpConfig()
        token = secrets.token_urlsafe(32)
        manager = StreamableHTTPSessionManager(
            _build_server(self._tools, self._tool_ctx), json_response=True, stateless=True
        )
        await self._stack.enter_async_context(manager.run())
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        config = uvicorn.Config(
            _BearerGate(manager, token), lifespan="off", log_level="warning", access_log=False
        )
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve(sockets=[sock]))
        self._stack.push_async_callback(self._stop, server, task, sock)
        while not server.started:
            if task.done():
                await self._stack.aclose()
                raise RuntimeError("codex 工具服务启动失败")
            await asyncio.sleep(0.01)
        url = f"http://127.0.0.1:{port}{_PATH}"
        names = ", ".join(_toml_string(spec.name) for spec in self._tools)
        overrides = {
            _PREFIX + "url": _toml_string(url),
            _PREFIX + "bearer_token_env_var": _toml_string(TOKEN_ENV),
            _PREFIX + "default_tools_approval_mode": _toml_string("approve"),
            _PREFIX + "enabled_tools": f"[{names}]",
            _PREFIX + "required": "true",
            _PREFIX + "tool_timeout_sec": str(TOOL_TIMEOUT_S),
        }
        return CodexMcpConfig(url=url, overrides=overrides, env={TOKEN_ENV: token})

    @staticmethod
    async def _stop(server: uvicorn.Server, task: asyncio.Task[None], sock: socket.socket) -> None:
        server.should_exit = True
        with contextlib.suppress(Exception):
            await task
        sock.close()

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()
