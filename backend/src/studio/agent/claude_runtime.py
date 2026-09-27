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
  标记为 `login`，成本只作参考。
- **工具**：原生 Read/Write/Edit/Glob/Grep/Bash，`ctx.allow_web` 时加
  WebSearch/WebFetch；业务 `ToolSpec` 经 `create_sdk_mcp_server` 变成进程内 MCP
  工具，handler 走 `invoke_tool`，`ToolResult.images` → MCP image content。
- **权限**：`PreToolUse` hook 拒绝写到 `ctx.write_scope` 之外的 Write/Edit/
  MultiEdit/NotebookEdit；Bash 不做事前检查（开 SDK sandbox，事后 `guard` 兜底）。
- **用量**：result 消息的 `total_cost_usd` 在恢复的会话里是累计值，这里按
  `CostLedger` 记录的上次累计值求差，`Usage` 是本轮的值。
- **取消/预算**：取消令牌置位或步数超限 → `interrupt()`；成本上限交给 SDK 的
  `max_budget_usd`（只统计本次 query() 调用的花费，即本轮）。

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
from studio.agent.tools import ToolContext, ToolSpec, invoke_tool
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
    """返回认证方式和传给 CLI 子进程的 `env`（合并在 `os.environ` 之上）。"""
    env: dict[str, str] = {}
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
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


class CostLedger:
    """每个 SDK 会话最近一次 result 的累计 `total_cost_usd`，一个会话一个 JSON 文件。

    落盘而不是放内存：进程重启后恢复的会话，第一条 result 就带着之前各轮的累计值。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, session_id: str) -> Path | None:
        if not _SESSION_ID_RE.match(session_id):
            return None
        return self._root / f"{session_id}.json"

    def total(self, session_id: str) -> float:
        path = self._path(session_id)
        if path is None:
            return 0.0
        try:
            return float(json.loads(path.read_text(encoding="utf-8"))["total_cost_usd"])
        except (OSError, ValueError, KeyError, TypeError):
            return 0.0

    def record(self, session_id: str, total: float) -> None:
        path = self._path(session_id)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"total_cost_usd": total}), encoding="utf-8")
        tmp.replace(path)


def write_denial_reason(workdir: Path, scope: WriteScope, tool_input: dict[str, Any]) -> str | None:
    """Write/Edit 类工具的目标不在 `scope` 内时返回拒绝原因，否则 `None`。"""
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    allowed = "、".join(scope.writable) or "（无）"
    if not isinstance(raw, str) or not raw:
        return f"无法确定写入目标路径，已拒绝。本阶段可写：{allowed}"
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
    tool_ctx = ToolContext(
        project_id=ctx.project_id,
        stage=ctx.stage,
        workdir=ctx.workdir,
        record_tool_write=ctx.record_tool_write,
    )

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
                images.append(events.ImageData(source["media_type"], source["data"]))
            else:  # MCP shape
                images.append(events.ImageData(block["mimeType"], block["data"]))
    return "\n".join(texts), images


@dataclass
class _Turn:
    session_id: str | None
    steps: int = 0
    budget_hit: bool = False
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
        hook = HookMatcher(
            matcher="|".join(GUARDED_WRITE_TOOLS),
            hooks=[_write_scope_hook(ctx.workdir.resolve(), ctx.write_scope)],
        )
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
            hooks={"PreToolUse": [hook]},
            sandbox=SANDBOX,
            include_partial_messages=True,
            # The prompt embeds workspace-derived text (preamble); never expand @paths in it.
            verbatim_prompts=True,
            max_budget_usd=ctx.budget.max_cost_usd if auth == "api_key" else None,
        )

    async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
        profile = ctx.model_profile
        try:
            auth, env = build_env(
                profile.api_key_env, profile.base_url, self._environ, self._claude_dir
            )
        except MissingApiKeyError as exc:
            yield events.TurnEnd(resume_ref=ctx.resume_ref, status="failed", error=str(exc))
            return

        client = self._client_factory(self._options(ctx, auth, env))
        turn = _Turn(session_id=ctx.resume_ref)
        watcher: asyncio.Task[None] | None = None
        max_steps = ctx.budget.max_steps
        try:
            await client.connect()
            watcher = asyncio.create_task(_interrupt_on_cancel(ctx.cancel_token, client, turn))
            await client.query(_prompt(ctx.user_input))
            async for message in client.receive_response():
                for event in _convert(message, turn):
                    yield event
                    if isinstance(event, events.ToolCall):
                        turn.steps += 1
                        if max_steps is not None and turn.steps > max_steps:
                            turn.budget_hit = True
                            await _interrupt(client, turn)
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
        usage_event = events.Usage(
            input_tokens=input_tokens,
            output_tokens=int(usage.get("output_tokens") or 0),
            cost_usd=self._turn_cost(ctx.resume_ref, result),
            auth=auth,
        )

        error: str | None = None
        if turn.budget_hit or result.subtype == "error_max_budget_usd":
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

    def _turn_cost(self, resume_ref: str | None, result: ResultMessage) -> float:
        """本轮花费 = 本次累计值 − 上次记录的累计值。

        累计值比记录值小（会话 transcript 没存累计值、被 /clear 等），就把本次
        累计值当作本轮花费。累计值为 0（出错时可能被清零）不记录，免得下一轮
        把之前的花费重复计入。
        """
        cumulative = result.total_cost_usd or 0.0
        previous = self._ledger.total(resume_ref) if resume_ref else 0.0
        cost = cumulative - previous if cumulative >= previous else cumulative
        if cumulative > 0:
            self._ledger.record(result.session_id, cumulative)
        return cost


def register_claude(factory: RuntimeFactory, settings: Settings) -> None:
    """把 `claude` 运行时注册进 `factory`（控制者裁定 R2）；没有 key 也可以注册，
    缺 key 的问题在对应的 turn 里报 `failed`。
    """
    data_dir = settings.data_dir
    factory.register("claude", lambda: ClaudeRuntime(data_dir))
