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
  （开 SDK sandbox：拒读仓库与数据目录、放回本轮工作区，TD-1；事后 `guard` 兜底写入）。
  继承来的名字像密钥的环境变量一律置空。各阶段暂不开联网（M4 带域名白名单再开）。
  剩余风险见 docs/references/claude-agent-sdk.md。
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

同包拆分（M1x T8）：环境变量在 `claude_env`，读写范围 hook 与 Bash sandbox 在
`claude_scope`，SDK 消息与事件的转换、业务工具桥接在 `claude_messages`。
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
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    Message,
    ResultMessage,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import HookEvent, McpServerConfig

from studio.agent import events
from studio.agent.claude_env import MissingApiKeyError, build_env
from studio.agent.claude_messages import (
    MCP_PREFIX,
    MCP_SERVER_NAME,
    SdkTurn,
    build_sdk_tool,
    convert_message,
    prompt_input,
)
from studio.agent.claude_scope import (
    GUARDED_WRITE_TOOLS,
    READ_TOOLS,
    read_scope_hook,
    sandbox_settings,
    write_scope_hook,
)
from studio.agent.claude_web import (
    WEB_FETCH_TOOL,
    WEB_SEARCH_TOOL,
    web_fetch_hook,
    web_search_collect_hook,
)
from studio.agent.runtime import CancelToken, RuntimeFactory, TurnContext
from studio.config import Settings
from studio.config import repo_root as default_repo_root

logger = logging.getLogger(__name__)

MAX_BUFFER_BYTES = 8 * 1024 * 1024
"""SDK 读 CLI 单行 JSON 的缓冲区上限（默认 1 MiB）。CLI 把工具结果里的图片写两份，真实会话里一行
就到了 1 054 050 字节；提高上限是兜底，第一道防线仍是 `agent.tools` 与 `stages.common.picture`
的预算。已经带着超限消息的历史会话也靠它继续（追加轮会重放这条历史）。"""

BUILTIN_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
WEB_TOOLS = ["WebSearch", "WebFetch"]


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


async def _interrupt(client: SdkClient, turn: SdkTurn) -> None:
    if turn.interrupted:
        return
    turn.interrupted = True
    try:
        await client.interrupt()
    except Exception:
        # The runner force-cancels the task after its grace period anyway.
        logger.exception("Claude SDK interrupt() 失败")


async def _interrupt_on_cancel(token: CancelToken, client: SdkClient, turn: SdkTurn) -> None:
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


class ClaudeRuntime:
    def __init__(
        self,
        data_dir: Path,
        *,
        repo_root: Path | None = None,
        client_factory: ClientFactory = _default_client,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._repo_root = repo_root if repo_root is not None else default_repo_root()
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
            mcp_tool_names = [MCP_PREFIX + spec.name for spec in ctx.tools]
        workdir = ctx.workdir.resolve()
        write_hook = HookMatcher(
            matcher="|".join(GUARDED_WRITE_TOOLS),
            hooks=[write_scope_hook(workdir, ctx.write_scope)],
        )
        read_hook = HookMatcher(matcher="|".join(READ_TOOLS), hooks=[read_scope_hook(workdir)])
        pre_hooks = [write_hook, read_hook]
        post_hooks: list[HookMatcher] = []
        if ctx.allow_web:
            # Native web mode: apply the same "URL source" rule as the self-built
            # fetch_url tool (TD-39).
            pre_hooks.append(
                HookMatcher(
                    matcher=WEB_FETCH_TOOL, hooks=[web_fetch_hook(ctx.engine, ctx.session_id)]
                )
            )
            post_hooks.append(
                HookMatcher(
                    matcher=WEB_SEARCH_TOOL, hooks=[web_search_collect_hook(ctx.session_id)]
                )
            )
        hooks: dict[HookEvent, list[HookMatcher]] = {"PreToolUse": pre_hooks}
        if post_hooks:
            hooks["PostToolUse"] = post_hooks
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
            hooks=hooks,
            sandbox=sandbox_settings(workdir, self._repo_root, self._data_dir),
            include_partial_messages=True,
            # Best effort: models that think return summarized text, others return none.
            thinking={"type": "adaptive", "display": "summarized"},
            effort=ctx.effort,
            # The prompt embeds workspace-derived text (preamble); never expand @paths in it.
            verbatim_prompts=True,
            max_buffer_size=MAX_BUFFER_BYTES,
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

        turn = SdkTurn(session_id=ctx.resume_ref)
        watcher: asyncio.Task[None] | None = None
        client: SdkClient | None = None
        try:
            client = self._client_factory(self._options(ctx, auth, env))
            if not await _connect_unless_cancelled(client, ctx.cancel_token):
                yield events.TurnEnd(resume_ref=ctx.resume_ref, status="cancelled")
                return
            watcher = asyncio.create_task(_interrupt_on_cancel(ctx.cancel_token, client, turn))
            turn.queried = True
            await client.query(prompt_input(ctx.user_input))
            async for message in client.receive_response():
                # Step budget: the runner counts ToolCalls and stops the turn via
                # the cancel token, which the watcher turns into interrupt() (TD-18).
                for event in convert_message(message, turn):
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
        self, ctx: TurnContext, auth: events.AuthMode, turn: SdkTurn
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
            cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
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
    root = default_repo_root()
    factory.register("claude", lambda: ClaudeRuntime(data_dir, repo_root=root))
