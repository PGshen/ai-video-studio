"""Claude Agent SDK 适配器（设计 §4.1–§4.3；SDK 行为见 docs/references/claude-agent-sdk.md）。

每一轮新建一个 `ClaudeSDKClient`（为了 `interrupt()`），`resume=ctx.resume_ref`
接上 SDK 会话，结束时 `TurnEnd.resume_ref` 带回 SDK 的 `session_id`。

- **认证**：`model_profile.api_key_env` 有值 → 从该环境变量读 key 注入子进程
  环境，并把 `CLAUDE_CONFIG_DIR` 指向 `<data_dir>/claude/`（会话存储随之移到
  数据目录；API key 模式下这一点待实测，登录模式的默认位置与恢复已在 T15 实测）；
  环境变量缺失 → 本轮直接 `failed`。为空 →
  本机登录模式：把 `LOGIN_BLANKED_ENV` 置空（SDK 把 `env` 合并在
  `os.environ` 之上，无法删除键，CLI 把空值当作未设置），不改
  `CLAUDE_CONFIG_DIR`（改了会读不到 macOS 钥匙串里的登录凭据），`Usage.auth`
  标记为 `login`，成本只作参考。两种模式都先把父进程继承来的宿主变量置空
  （`HOST_BLANKED_ENV`：Claude Code / 桌面版注入的 OAuth、会话、provider、模型覆盖等），
  `make dev`/`make smoke` 从 Claude Code 里启动时也不会被宿主环境带偏。
- **工具**：原生 Read/Write/Edit/Glob/Grep/Bash，`ctx.allow_web` 时加
  WebSearch/WebFetch；业务 `ToolSpec` 经 `create_sdk_mcp_server` 变成进程内 MCP
  工具，handler 走 `invoke_tool`，`ToolResult.images` → MCP image content。
- **权限**：`PreToolUse` hook 拒绝写到 `ctx.write_scope` 之外的 Write/Edit/
  MultiEdit/NotebookEdit，拒绝读工作区之外的 Read/Glob/Grep；Bash 不做事前检查
  （开 SDK sandbox，事后 `guard` 兜底）。继承来的名字像密钥的环境变量一律置空。
  剩余风险（WebFetch 放行所有域名、sandbox 只管 Bash 且不限制读）见
  docs/references/claude-agent-sdk.md。
- **用量**：result 消息的 `total_cost_usd` 在恢复的会话里是累计值，这里按
  `CostLedger`（键为 SDK 会话 id）记录的上次累计值求差，`Usage` 是本轮的值。
  一轮没拿到 result（被强制取消、出错）时账本标"待校准"，那一轮的花费并入
  下一轮的差值，`Usage.includes_carryover` 标注（TD-11）。
- **取消/预算**：开始前已取消 → 不启动 CLI；connect 期间取消 → 放弃 connect
  立即结束（TD-12）；之后取消令牌置位 → `interrupt()`。步数由 TurnRunner 计数，
  超限时它置位取消令牌，本轮由 runner 记为 `budget_exceeded`（TD-18）。成本上限为 0 →
  不启动 CLI，直接 `budget_exceeded`；其余交给 SDK 的 `max_budget_usd`（只统计
  本次 query() 调用的花费，即本轮）。

SDK 边界只有 `SdkClient` 协议和 `client_factory`：测试注入回放消息序列的假客户端。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    Message,
    ResultMessage,
    SdkMcpTool,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import (
    HookCallback,
    HookContext,
    HookInput,
    HookJSONOutput,
    McpServerConfig,
    SandboxSettings,
)

from studio.agent import events
from studio.agent.runtime import CancelToken, RuntimeFactory, TurnContext, UserInput
from studio.agent.tools import ToolSpec, invoke_tool
from studio.config import Settings
from studio.workspace.scope import WriteScope, is_writable

logger = logging.getLogger(__name__)

BUILTIN_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
WEB_TOOLS = ["WebSearch", "WebFetch"]
GUARDED_WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
MCP_SERVER_NAME = "studio"
_MCP_PREFIX = f"mcp__{MCP_SERVER_NAME}__"

LOGIN_BLANKED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
"""登录模式下置空的环境变量：任一有值都会覆盖本机登录凭据。"""

DEFAULT_BASE_URL = "https://api.anthropic.com"
"""继承来的 `ANTHROPIC_BASE_URL` 被替换成的值（模型配置没设 `base_url` 时）。不置空：
CLI 里有 `process.env.X ?? process.env.ANTHROPIC_BASE_URL` 这样的写法，空串不算"未设置"。"""

HOST_BLANKED_ENV = frozenset(
    {
        # Credentials / auth routing a parent shell may carry.
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_PROFILE",
        "ANTHROPIC_UNIX_SOCKET",
        "ANTHROPIC_CUSTOM_HEADERS",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
        "CLAUDE_CODE_OAUTH_SCOPES",
        "CLAUDE_CODE_OAUTH_CLIENT_ID",
        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
        "CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR",
        "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST",
        # Model overrides (the profile's `model` must win).
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_FABLE_MODEL",
        "ANTHROPIC_SMALL_FAST_MODEL",
        # Provider switches (first-party API only in M1).
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_USE_GATEWAY",
        "CLAUDE_CODE_USE_MANTLE",
        "CLAUDE_CODE_USE_ANTHROPIC_AWS",
        "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
        # Host-integration markers set by Claude Code / the desktop app.
        "CLAUDE_CODE_EXECPATH",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING",
        "CLAUDE_CODE_EMIT_TOOL_USE_SUMMARIES",
        "CLAUDE_CODE_TERMINAL_MCP_TOOLS",
        "CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL",
        "CLAUDE_CODE_REPORT_FINDINGS",
        "CLAUDE_CODE_EAGER_FLUSH",
    }
)
"""父进程（例如在 Claude Code / Claude 桌面版里启动的 shell）可能带着、会改变认证方式、
模型、目标服务或宿主集成行为的变量；继承到的一律置空（CLI 按 JS 真值判断，空串即未设置）。
不动 `CLAUDE_CODE_ENTRYPOINT`（SDK 自己设 `sdk-py`）、`CLAUDE_CODE_SDK_READS_SESSION_STATE`
（SDK 只在键不存在时才设 `1`）、`CLAUDE_CONFIG_DIR`（登录模式靠它找到用户自己的登录凭据）。"""

HOST_BLANKED_PREFIXES = (
    "CLAUDE_CODE_HOST_",
    "CLAUDE_CODE_SDK_HAS_",
    "CLAUDE_CODE_MESSAGING_",
    "CLAUDE_CODE_SESSION_",
    "CLAUDE_CODE_REMOTE",
    "CLAUDE_CODE_DESKTOP_",
)
"""按前缀置空的宿主集成变量（宿主会话 id、消息 socket、宿主代管的 OAuth 刷新等）。"""

SECRET_NAME_RE = re.compile(r"(?:^|_)(?:API_?KEY|KEY|TOKEN|SECRET|PASSWORD|PASSWD)S?(?:_|$)")
"""名字像密钥的环境变量（按下划线分段匹配，大小写不敏感）：继承来的一律置空，
agent 的 Bash 就读不到其他服务的 key（例如 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY`），
再经 WebFetch 外发（I5）。按段匹配是为了不误伤 `SSH_AUTH_SOCK`、`KEYCHAIN_*` 之类。
当前配置用到的 `ANTHROPIC_API_KEY` 在 API key 模式下随后被重新写入。"""

READ_TOOLS = ("Read", "Glob", "Grep")
"""受读取范围 hook 约束的原生只读工具：路径必须落在工作区内（含 `upstream/`）。"""

SANDBOX: SandboxSettings = {
    "enabled": True,
    "autoAllowBashIfSandboxed": True,
    # Without this the model can opt out per command via dangerouslyDisableSandbox.
    "allowUnsandboxedCommands": False,
}
"""Bash sandbox。R3 已在 T15 实测（macOS，2026-09-28）：工作区外写入、外网都被拦住，保留 Bash。"""


class SdkClient(Protocol):
    """`ClaudeSDKClient` 中本模块用到的部分。"""

    async def connect(self) -> None: ...

    async def query(self, prompt: str | AsyncIterable[dict[str, Any]]) -> None: ...

    def receive_response(self) -> AsyncIterator[Message]: ...

    async def interrupt(self) -> None: ...

    async def disconnect(self) -> None: ...


ClientFactory = Callable[[ClaudeAgentOptions], SdkClient]


def _default_client(options: ClaudeAgentOptions) -> SdkClient:
    return ClaudeSDKClient(options=options)


class MissingApiKeyError(Exception):
    pass


def build_env(
    api_key_env: str | None,
    base_url: str | None,
    environ: Mapping[str, str],
    claude_dir: Path,
) -> tuple[events.AuthMode, dict[str, str]]:
    """返回认证方式和传给 CLI 子进程的 `env`（合并在 `os.environ` 之上）。

    继承来的宿主变量（`HOST_BLANKED_ENV`、`HOST_BLANKED_PREFIXES`）和名字像密钥的
    变量（`SECRET_NAME_RE`，含模型配置的 `api_key_env` 本身）先置空，
    `ANTHROPIC_BASE_URL` 换成模型配置的 `base_url` 或官方地址，再按认证方式覆盖。
    """
    env: dict[str, str] = {
        name: ""
        for name in environ
        if name in HOST_BLANKED_ENV
        or name.startswith(HOST_BLANKED_PREFIXES)
        or SECRET_NAME_RE.search(name.upper())
    }
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    elif "ANTHROPIC_BASE_URL" in environ:
        env["ANTHROPIC_BASE_URL"] = DEFAULT_BASE_URL
    if api_key_env is None:
        env.update(dict.fromkeys(LOGIN_BLANKED_ENV, ""))
        return "login", env
    key = environ.get(api_key_env)
    if not key:
        raise MissingApiKeyError(f"环境变量 {api_key_env} 未设置，无法调用 Claude（API key 模式）")
    env["ANTHROPIC_API_KEY"] = key
    env["ANTHROPIC_AUTH_TOKEN"] = ""
    env["CLAUDE_CONFIG_DIR"] = str(claude_dir)
    return "api_key", env


_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,128}$")


@dataclass(frozen=True)
class LedgerEntry:
    total: float
    """该会话最近一次拿到的 result 的累计 `total_cost_usd`（上次已知累计）。"""
    unsettled: bool = False
    """之后有一轮没拿到 result（强制取消或出错），那一轮的花费还没算进任何一轮。"""


class CostLedger:
    """每个 SDK 会话的 `LedgerEntry`，一个会话一个 JSON 文件，键是 SDK 会话 id。

    落盘而不是放内存：进程重启后恢复的会话，第一条 result 就带着之前各轮的累计值。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, session_id: str) -> Path | None:
        if not _SESSION_ID_RE.match(session_id):
            return None
        return self._root / f"{session_id}.json"

    def get(self, session_id: str) -> LedgerEntry | None:
        path = self._path(session_id)
        if path is None or not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return LedgerEntry(float(raw["total_cost_usd"]), bool(raw.get("unsettled", False)))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def total(self, session_id: str) -> float:
        entry = self.get(session_id)
        return entry.total if entry is not None else 0.0

    def record(self, session_id: str, total: float) -> None:
        """记下新的累计值（同时清掉"待校准"标记）。"""
        self._write(session_id, LedgerEntry(total))

    def mark_unsettled(self, session_id: str) -> None:
        """本轮没拿到 result：保留上次已知累计，标记"待校准"，下一轮求差时带上。"""
        self._write(session_id, LedgerEntry(self.total(session_id), unsettled=True))

    def _write(self, session_id: str, entry: LedgerEntry) -> None:
        path = self._path(session_id)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = {"total_cost_usd": entry.total, "unsettled": entry.unsettled}
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)


_PADDING = "\ufeff"
"""JS `String.prototype.trim()` also strips U+FEFF, which Python's `str.strip()` keeps."""


def _padded(raw: str) -> bool:
    """首尾带空白（含 U+FEFF）的路径/模式一律拒绝。

    内置 CLI 的 `expandPath` 先 `trim()` 再展开 `~`、解析相对路径，而 hook 按原串判断：
    `" /etc/passwd"` 在 hook 看来是工作区内的相对路径，CLI 实际读的却是 `/etc/passwd`。
    直接拒绝比模仿 CLI 的 trim 规则更稳妥，正常的工具调用不会带这样的路径。
    """
    return raw != raw.strip() or raw.strip(_PADDING) != raw


def write_denial_reason(workdir: Path, scope: WriteScope, tool_input: dict[str, Any]) -> str | None:
    """Write/Edit 类工具的目标不在 `scope` 内时返回拒绝原因，否则 `None`。"""
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    allowed = "、".join(scope.writable) or "（无）"
    if not isinstance(raw, str) or not raw:
        return f"无法确定写入目标路径，已拒绝。本阶段可写：{allowed}"
    if _padded(raw):
        return f"路径 {raw!r} 首尾带空白，已拒绝。本阶段可写：{allowed}"
    if raw.startswith("~"):
        return f"{raw} 在项目工作区之外，已拒绝。本阶段可写：{allowed}"
    target = Path(raw)
    if not target.is_absolute():
        target = workdir / target
    try:
        relpath = target.resolve().relative_to(workdir).as_posix()
    except ValueError:
        return f"{raw} 在项目工作区之外，已拒绝。本阶段可写：{allowed}"
    if not is_writable(scope, relpath):
        return f"{relpath} 不在本阶段可写范围内，已拒绝。本阶段可写：{allowed}"
    return None


def _escapes(workdir: Path, raw: str) -> bool:
    """`raw`（相对 `workdir` 或绝对路径）解析符号链接和 `..` 之后是否落在 `workdir` 外。

    以 `~` 开头的一律算越界（F1）：内置 CLI 的 `expandPath` 会把 `~`、`~/…` 展开成家目录，
    而 `Path` 把它当普通相对段。`~user/…` CLI 不展开（按工作区内的相对路径处理），
    这里同样拒绝，免得依赖这一细节。首尾带空白的也算越界（见 `_padded`）。
    """
    if _padded(raw) or raw.startswith("~"):
        return True
    target = Path(raw)
    if not target.is_absolute():
        target = workdir / target
    resolved = target.resolve()
    return resolved != workdir and workdir not in resolved.parents


def read_denial_reason(workdir: Path, tool_name: str, tool_input: dict[str, Any]) -> str | None:
    """Read/Glob/Grep 的目标不在工作区内时返回拒绝原因，否则 `None`（I5）。

    - Read：`file_path` 必填，解析后必须在工作区内；
    - Glob/Grep：`path` 缺省即工作区（cwd），给了就必须在工作区内；glob 模式
      （Glob 的 `pattern`、Grep 的 `glob`）不能是绝对路径、以 `~` 开头、含 `..` 或首尾带空白。
    """
    refuse = "只能读取项目工作区内的文件，已拒绝：{}"
    if tool_name == "Read":
        raw = tool_input.get("file_path")
        if not isinstance(raw, str) or not raw:
            return refuse.format("无法确定读取路径")
        return refuse.format(raw) if _escapes(workdir, raw) else None

    raw_path = tool_input.get("path")
    if raw_path is not None and (not isinstance(raw_path, str) or _escapes(workdir, raw_path)):
        return refuse.format(raw_path)
    pattern = tool_input.get("pattern" if tool_name == "Glob" else "glob")
    if isinstance(pattern, str) and (
        _padded(pattern) or pattern.startswith(("/", "~")) or ".." in Path(pattern).parts
    ):
        return refuse.format(pattern)
    return None


def _read_scope_hook(workdir: Path) -> HookCallback:
    async def hook(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}
        reason = read_denial_reason(workdir, input_data["tool_name"], input_data["tool_input"])
        if reason is None:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return hook


def _write_scope_hook(workdir: Path, scope: WriteScope) -> HookCallback:
    async def hook(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}
        reason = write_denial_reason(workdir, scope, input_data["tool_input"])
        if reason is None:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return hook


def build_sdk_tool(spec: ToolSpec, ctx: TurnContext) -> SdkMcpTool[Any]:
    """把业务 `ToolSpec` 转成 SDK 的进程内 MCP 工具；调用统一走 `invoke_tool`。"""
    tool_ctx = ctx.tool_context()

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        result = await invoke_tool(spec, tool_ctx, args)
        content: list[dict[str, Any]] = [{"type": "text", "text": result.text}]
        content += [
            {"type": "image", "data": image.data_base64, "mimeType": image.media_type}
            for image in result.images
        ]
        return {"content": content, "is_error": result.is_error}

    return SdkMcpTool(
        name=spec.name,
        description=spec.description,
        input_schema=spec.input_model.model_json_schema(),
        handler=handler,
    )


def _prompt(user_input: UserInput) -> str | AsyncIterable[dict[str, Any]]:
    if not user_input.images:
        return user_input.text

    async def stream() -> AsyncIterator[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_input.text}]
        content += [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.media_type,
                    "data": image.data_base64,
                },
            }
            for image in user_input.images
        ]
        yield {
            "type": "user",
            "message": {"role": "user", "content": content},
            "parent_tool_use_id": None,
        }

    return stream()


def _tool_result_content(
    content: str | list[dict[str, Any]] | None,
) -> tuple[str, list[events.ImageData]]:
    if content is None:
        return "", []
    if isinstance(content, str):
        return content, []
    texts: list[str] = []
    images: list[events.ImageData] = []
    for block in content:
        kind = block.get("type")
        if kind == "text":
            texts.append(str(block.get("text", "")))
        elif kind == "image":
            source = block.get("source")
            if isinstance(source, dict):  # Anthropic API shape
                media_type, data = source.get("media_type"), source.get("data")
            else:  # MCP shape
                media_type, data = block.get("mimeType"), block.get("data")
            if isinstance(media_type, str) and isinstance(data, str):
                images.append(events.ImageData(media_type, data))
            else:
                logger.warning("跳过缺少 media type 或数据的图片块：%s", sorted(block))
    return "\n".join(texts), images


@dataclass
class _Turn:
    session_id: str | None
    queried: bool = False
    interrupted: bool = False
    result: ResultMessage | None = None


async def _interrupt(client: SdkClient, turn: _Turn) -> None:
    if turn.interrupted:
        return
    turn.interrupted = True
    try:
        await client.interrupt()
    except Exception:
        # The runner force-cancels the task after its grace period anyway.
        logger.exception("Claude SDK interrupt() 失败")


async def _interrupt_on_cancel(token: CancelToken, client: SdkClient, turn: _Turn) -> None:
    await token.wait()
    await _interrupt(client, turn)


async def _connect_unless_cancelled(client: SdkClient, token: CancelToken) -> bool:
    """`connect()`，但取消令牌先置位时立即放弃（TD-12）并返回 `False`。

    SDK 的 `connect()` 被取消时自己会 `disconnect()` 清理已启动的子进程
    （`client.py: connect` 的 `except BaseException`）。
    """
    connecting = asyncio.ensure_future(client.connect())
    cancelled = asyncio.ensure_future(token.wait())
    try:
        await asyncio.wait({connecting, cancelled}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        cancelled.cancel()
        if not connecting.done():
            connecting.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connecting
    if connecting.cancelled():
        return False
    connecting.result()  # re-raise connect errors
    return not token.is_cancelled


def _convert(message: Message, turn: _Turn) -> list[events.AgentEvent]:
    if isinstance(message, SystemMessage):
        session_id = message.data.get("session_id")
        if isinstance(session_id, str):
            turn.session_id = session_id
        return []
    if isinstance(message, StreamEvent | AssistantMessage | ResultMessage) and message.session_id:
        turn.session_id = message.session_id
    if isinstance(message, StreamEvent | AssistantMessage | UserMessage):
        if message.parent_tool_use_id is not None:
            return []  # subagent traffic
    if isinstance(message, StreamEvent):
        event = message.event
        delta = event.get("delta") or {}
        if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
            return [events.TextDelta(text=delta.get("text", ""))]
        return []
    converted: list[events.AgentEvent] = []
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock) and block.text:
                converted.append(events.TextBlock(text=block.text))
            elif isinstance(block, ToolUseBlock):
                name = block.name.removeprefix(_MCP_PREFIX)
                converted.append(events.ToolCall(call_id=block.id, name=name, args=block.input))
    elif isinstance(message, UserMessage) and isinstance(message.content, list):
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                text, images = _tool_result_content(block.content)
                converted.append(
                    events.ToolResult(
                        call_id=block.tool_use_id,
                        text=text,
                        images=images,
                        is_error=bool(block.is_error),
                    )
                )
    return converted


class ClaudeRuntime:
    def __init__(
        self,
        data_dir: Path,
        *,
        client_factory: ClientFactory = _default_client,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._claude_dir = data_dir / "claude"
        self._ledger = CostLedger(self._claude_dir / "studio-cost-ledger")
        self._client_factory = client_factory
        self._environ = environ if environ is not None else os.environ

    def _options(
        self, ctx: TurnContext, auth: events.AuthMode, env: dict[str, str]
    ) -> ClaudeAgentOptions:
        tools = BUILTIN_TOOLS + (WEB_TOOLS if ctx.allow_web else [])
        mcp_servers: dict[str, McpServerConfig] = {}
        mcp_tool_names: list[str] = []
        if ctx.tools:
            sdk_tools = [build_sdk_tool(spec, ctx) for spec in ctx.tools]
            mcp_servers[MCP_SERVER_NAME] = create_sdk_mcp_server(MCP_SERVER_NAME, tools=sdk_tools)
            mcp_tool_names = [_MCP_PREFIX + spec.name for spec in ctx.tools]
        workdir = ctx.workdir.resolve()
        write_hook = HookMatcher(
            matcher="|".join(GUARDED_WRITE_TOOLS),
            hooks=[_write_scope_hook(workdir, ctx.write_scope)],
        )
        read_hook = HookMatcher(matcher="|".join(READ_TOOLS), hooks=[_read_scope_hook(workdir)])
        return ClaudeAgentOptions(
            model=ctx.model_profile.model,
            cwd=ctx.workdir,
            system_prompt=ctx.system_prompt,
            tools=tools,
            allowed_tools=tools + mcp_tool_names,
            mcp_servers=mcp_servers,
            strict_mcp_config=True,
            setting_sources=[],
            permission_mode="acceptEdits",
            resume=ctx.resume_ref,
            env=env,
            hooks={"PreToolUse": [write_hook, read_hook]},
            sandbox=SANDBOX,
            include_partial_messages=True,
            # The prompt embeds workspace-derived text (preamble); never expand @paths in it.
            verbatim_prompts=True,
            max_budget_usd=ctx.budget.max_cost_usd if auth == "api_key" else None,
        )

    async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
        profile = ctx.model_profile
        # TD-12: never start the CLI for a turn that is already cancelled, or whose
        # cost budget is zero (the CLI does not enforce max_budget_usd=0).
        if ctx.cancel_token.is_cancelled:
            yield events.TurnEnd(resume_ref=ctx.resume_ref, status="cancelled")
            return
        if ctx.budget.max_cost_usd is not None and ctx.budget.max_cost_usd <= 0:
            yield events.TurnEnd(
                resume_ref=ctx.resume_ref,
                status="budget_exceeded",
                error="本轮成本上限为 0，未启动模型",
            )
            return
        try:
            auth, env = build_env(
                profile.api_key_env, profile.base_url, self._environ, self._claude_dir
            )
        except MissingApiKeyError as exc:
            yield events.TurnEnd(resume_ref=ctx.resume_ref, status="failed", error=str(exc))
            return

        turn = _Turn(session_id=ctx.resume_ref)
        watcher: asyncio.Task[None] | None = None
        client: SdkClient | None = None
        try:
            client = self._client_factory(self._options(ctx, auth, env))
            if not await _connect_unless_cancelled(client, ctx.cancel_token):
                yield events.TurnEnd(resume_ref=ctx.resume_ref, status="cancelled")
                return
            watcher = asyncio.create_task(_interrupt_on_cancel(ctx.cancel_token, client, turn))
            turn.queried = True
            await client.query(_prompt(ctx.user_input))
            async for message in client.receive_response():
                # Step budget: the runner counts ToolCalls and stops the turn via
                # the cancel token, which the watcher turns into interrupt() (TD-18).
                for event in _convert(message, turn):
                    yield event
                if isinstance(message, ResultMessage):
                    turn.result = message
        except Exception as exc:
            logger.exception("Claude SDK 调用失败")
            yield events.TurnEnd(
                resume_ref=turn.session_id,
                status="failed",
                error=f"Claude SDK 出错：{type(exc).__name__}: {exc}",
            )
            return
        finally:
            if watcher is not None:
                watcher.cancel()
            if turn.queried and turn.result is None and turn.session_id:
                # No result (forced cancel / error): this turn's spend is only
                # knowable from the next result's cumulative total (TD-11).
                self._ledger.mark_unsettled(turn.session_id)
            if client is not None:
                with contextlib.suppress(Exception):
                    await client.disconnect()

        for event in self._finish(ctx, auth, turn):
            yield event

    def _finish(
        self, ctx: TurnContext, auth: events.AuthMode, turn: _Turn
    ) -> list[events.AgentEvent]:
        result = turn.result
        if result is None:
            return [
                events.TurnEnd(
                    resume_ref=turn.session_id,
                    status="failed",
                    error="Claude SDK 没有返回结果消息",
                )
            ]
        usage = result.usage or {}
        input_tokens = sum(
            int(usage.get(key) or 0)
            for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        cost, carryover = self._turn_cost(ctx.resume_ref, result)
        usage_event = events.Usage(
            input_tokens=input_tokens,
            output_tokens=int(usage.get("output_tokens") or 0),
            cost_usd=cost,
            auth=auth,
            includes_carryover=carryover,
        )

        error: str | None = None
        if result.subtype == "error_max_budget_usd":
            status: events.TurnStatus = "budget_exceeded"
        elif ctx.cancel_token.is_cancelled or (result.terminal_reason or "").startswith("aborted"):
            status = "cancelled"
        elif result.is_error:
            status = "failed"
            error = "; ".join(result.errors or []) or result.result or result.subtype
        else:
            status = "done"
        end = events.TurnEnd(resume_ref=result.session_id, status=status, error=error)
        return [usage_event, end]

    def _turn_cost(self, resume_ref: str | None, result: ResultMessage) -> tuple[float, bool]:
        """返回（本轮花费, 是否含上一轮残余）。本轮花费 = 本次累计值 − 上次已知累计值。

        账本键是 result 的 `session_id`（TD-11）；该会话还没有记录时退回
        `resume_ref` 的记录（例如 fork 出的新会话，累计值接着被恢复的 transcript）。
        没有 `resume_ref` 的新会话累计值从 0 开始，不查账本。
        累计值比记录值小（transcript 没存累计值、被 /clear 等），就把本次累计值
        当作本轮花费。累计值为 0（出错时可能被清零）不记录，免得下一轮把之前的
        花费重复计入。记录带"待校准"标记（上一轮没拿到 result）时，求差得到的
        花费含那一轮的残余，返回 `True` 供 `Usage.includes_carryover` 标注。
        """
        cumulative = result.total_cost_usd or 0.0
        entry: LedgerEntry | None = None
        if resume_ref:  # a fresh (non-resumed) session's total starts at zero
            entry = self._ledger.get(result.session_id) or self._ledger.get(resume_ref)
        previous = entry.total if entry is not None else 0.0
        carryover = False
        if cumulative >= previous:
            cost = cumulative - previous
            carryover = entry is not None and entry.unsettled and cumulative > 0
        else:
            cost = cumulative
        if cumulative > 0:
            self._ledger.record(result.session_id, cumulative)
        return cost, carryover


def register_claude(factory: RuntimeFactory, settings: Settings) -> None:
    """把 `claude` 运行时注册进 `factory`（控制者裁定 R2）；没有 key 也可以注册，
    缺 key 的问题在对应的 turn 里报 `failed`。
    """
    data_dir = settings.data_dir
    factory.register("claude", lambda: ClaudeRuntime(data_dir))
