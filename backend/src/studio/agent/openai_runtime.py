"""OpenAI Agents SDK 适配器（设计 §4.1–§4.3；SDK 行为见 docs/references/openai-agents-sdk.md）。

按 `model_profile.provider` 选两条路径：

- `openai` → `OpenAIResponsesModel`（显式 `AsyncOpenAI(api_key, base_url)`），原生
  `ApplyPatchTool`（`WorkspaceApplyPatchEditor`，经 `workspace.files` 落盘）+
  `ShellTool`（`LocalShellExecutor`，工作目录为工作区）；`ctx.allow_web` 时加托管
  `WebSearchTool`。
- `litellm` → `LitellmModel`（显式传 `api_key`/`base_url`，不改 `os.environ`），
  兜底文件工具（`fallback_tools`），不提供 Shell，M1 不提供联网工具（Tavily 在 M4）。

两条路径的业务 `ToolSpec` 都转成 `FunctionTool`，调用走 `invoke_tool`，图片结果
转成 `ToolOutputImage`（data URL）。

- **认证**：`api_key_env` 必填，每轮从环境变量读 key；缺失 → 本轮 `failed`。
- **会话**：`SQLiteSession(<session_id>, <data_dir>/openai_sessions.db)`；首轮生成
  新 id，`TurnEnd.resume_ref` 带回。发给模型的历史只保留最近 `history_turns` 轮
  （`session_input_callback` 在读取时裁剪，库里保留全部），更早的现状由上下文
  前言兜底（设计 §4.1）。
- **用量**：`RunHooks.on_llm_end` 取每次模型调用的 `response.usage`，按模型配置
  单价（美元 / 百万 token）算成本，每次调用产出一个 `Usage` 事件（TurnRunner 累加
  并强制成本预算）。配置了成本上限但缺单价 → 本轮直接 `failed`，免得预算形同虚设。
- **取消**：取消令牌置位 → `RunResultStreaming.cancel()`（immediate），`TurnEnd`
  状态 `cancelled`。步数/成本预算由 TurnRunner 判定后同样经取消令牌停止。

测试边界是 `model_factory`：注入 `agents.testing.ScriptedModel`，其余走真实的
`Runner.run_streamed`。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents import (
    Agent,
    ApplyPatchTool,
    FunctionTool,
    ItemHelpers,
    MaxTurnsExceeded,
    MessageOutputItem,
    Model,
    ModelResponse,
    ModelSettings,
    OpenAIResponsesModel,
    RawResponsesStreamEvent,
    RunConfig,
    RunContextWrapper,
    RunHooks,
    RunItemStreamEvent,
    Runner,
    RunResultStreaming,
    ShellCallOutcome,
    ShellCommandOutput,
    ShellCommandRequest,
    ShellResult,
    ShellTool,
    SQLiteSession,
    Tool,
    ToolCallItem,
    ToolCallOutputItem,
    ToolOutputImage,
    ToolOutputText,
    TResponseInputItem,
    UserError,
    WebSearchTool,
)
from agents.tool_context import ToolContext as SdkToolContext
from agents.usage import Usage as SdkUsage
from openai import AsyncOpenAI

from studio.agent import events
from studio.agent.apply_patch import WorkspaceApplyPatchEditor, to_workspace_relpath
from studio.agent.fallback_tools import build_fallback_tools
from studio.agent.runtime import CancelToken, RuntimeFactory, TurnContext, UserInput
from studio.agent.tools import ToolContext, ToolResult, ToolSpec, invoke_tool
from studio.config import Settings
from studio.db.repo.profiles import ModelProfileValue
from studio.workspace.files import ScopeError

logger = logging.getLogger(__name__)

SESSIONS_DB = "openai_sessions.db"
MAX_TURNS = 200
"""SDK 的 `max_turns`（模型调用次数上限）；SDK 默认 10 太小。真正的步数预算由
TurnRunner 按 `max_steps_per_turn` 强制，这里只是防失控的兜底。"""

SHELL_DEFAULT_TIMEOUT_S = 120.0
SHELL_MAX_TIMEOUT_S = 600.0
SHELL_MAX_OUTPUT_CHARS = 20_000
_SECRET_ENV_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)
"""名字匹配的环境变量不传给 Shell 子进程。只是减少 key **意外**泄露（例如命令
把环境打印出来）：Shell 没有沙箱，命令仍能读取本机任意文件（包括 `backend/.env`）。"""

ModelFactory = Callable[[ModelProfileValue, str], Model]


class TurnSetupError(Exception):
    """本轮无法开始（缺 key、未知 provider、缺单价）；错误信息直接进 `TurnEnd.error`。"""


def openai_client(profile: ModelProfileValue, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, base_url=profile.base_url)


SUPPORTED_PROVIDERS = ("openai", "litellm")


def _check_provider(profile: ModelProfileValue) -> None:
    if profile.provider not in SUPPORTED_PROVIDERS:
        raise TurnSetupError(
            f"OpenAI 运行时不支持 provider={profile.provider}（只支持 openai、litellm）"
        )


def build_model(profile: ModelProfileValue, api_key: str) -> Model:
    _check_provider(profile)
    if profile.provider == "openai":
        return OpenAIResponsesModel(
            model=profile.model, openai_client=openai_client(profile, api_key)
        )
    # Imported lazily: importing litellm takes seconds and is only needed on this path.
    from agents.extensions.models.litellm_model import LitellmModel

    return LitellmModel(model=profile.model, base_url=profile.base_url, api_key=api_key)


def turn_cost(profile: ModelProfileValue, input_tokens: int, output_tokens: int) -> float:
    """按模型配置单价（美元 / 百万 token）计算成本；缺单价的一侧按 0 计。

    缓存命中的输入 token 也按普通输入价计（宁可高估，和旧项目的做法一致）。
    """
    price_in = profile.price_input or 0.0
    price_out = profile.price_output or 0.0
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def _api_key(profile: ModelProfileValue, environ: Mapping[str, str]) -> str:
    if not profile.api_key_env:
        raise TurnSetupError(
            f"模型配置 {profile.name} 没有设置 api_key_env，OpenAI 运行时需要 API key"
        )
    key = environ.get(profile.api_key_env)
    if not key:
        raise TurnSetupError(f"环境变量 {profile.api_key_env} 未设置，无法调用模型 {profile.name}")
    return key


# ---- shell --------------------------------------------------------------


def _shell_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if not _SECRET_ENV_RE.search(name)}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（输出过长，已截断，共 {len(text)} 字符）"


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


async def _read_capped(
    stream: asyncio.StreamReader | None, cap: int, on_overflow: Callable[[], None]
) -> bytes:
    """读到 EOF，只保留前 `cap` 字节；超过时调用一次 `on_overflow`（杀进程组），
    之后继续读并丢弃，直到管道关闭。"""
    if stream is None:
        return b""
    kept = bytearray()
    overflowed = False
    while chunk := await stream.read(65536):
        room = cap - len(kept)
        if room > 0:
            kept += chunk[:room]
        if len(chunk) > room and not overflowed:
            overflowed = True
            on_overflow()
    return bytes(kept)


async def _wait_for_exit(proc: asyncio.subprocess.Process, timeout: float) -> bool:
    """等 shell 进程本身退出（`True`）或超时（`False`）。

    不能用 `proc.wait()`：asyncio 要等所有管道都关闭才让它返回，而后台子进程
    继承了 stdout，会一直拖到它们自己结束——那样就来不及在它们改工作区之前杀掉。
    `returncode` 在进程退出时就会被设置，这里轮询它。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while proc.returncode is None:
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.02)
    return True


_READER_DRAIN_TIMEOUT_S = 2.0
"""命令结束并杀掉进程组后，等管道读完的上限；逃出进程组（`setsid`）又占着管道的
进程会让读取一直挂起，超时后放弃读取。"""


class LocalShellExecutor:
    """`ShellTool` 的本地 executor：命令在工作区目录下逐条执行。

    **没有沙箱**：命令能读本机任意文件、写工作区内任意路径，不经过事前拦截；
    工作区内的越界改动由轮末的 `guard` 还原（设计 §4.3 第 2 道防线），工作区外的
    改动没有防线。

    每条命令在自己的进程组里运行（`start_new_session`）；命令结束（无论退出码）、
    超时、输出超限或被取消时都杀掉整个进程组，所以 `nohup ... &` 之类的后台进程
    不会活过这次调用——否则它们可能在轮末 `guard` 和快照之后才改工作区，改动会
    进入下一轮的基线、永远不会被还原。用 `setsid` 等方式主动脱离进程组的进程
    管不到。

    超时、输出超限或非零退出码的调用记进 `failed`，运行时据此把对应的
    `ToolResult` 标记为 `is_error`。
    """

    def __init__(
        self,
        workdir: Path,
        failed: set[str],
        *,
        default_timeout_s: float = SHELL_DEFAULT_TIMEOUT_S,
        max_output_chars: int = SHELL_MAX_OUTPUT_CHARS,
    ) -> None:
        self._workdir = workdir
        self._failed = failed
        self._default_timeout_s = default_timeout_s
        self._max_output_chars = max_output_chars

    async def __call__(self, request: ShellCommandRequest) -> ShellResult:
        action = request.data.action
        timeout = action.timeout_ms / 1000 if action.timeout_ms else self._default_timeout_s
        timeout = min(timeout, SHELL_MAX_TIMEOUT_S)
        limit = min(action.max_output_length or self._max_output_chars, self._max_output_chars)
        outputs: list[ShellCommandOutput] = []
        for command in action.commands:
            output, failed = await self._run(command, timeout, limit)
            outputs.append(output)
            if failed:
                self._failed.add(request.data.call_id)
            if output.status == "timeout":
                break
        return ShellResult(output=outputs)

    async def _run(
        self, command: str, timeout: float, limit: int
    ) -> tuple[ShellCommandOutput, bool]:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=self._workdir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_shell_env(),
            start_new_session=True,
        )
        overflowed = False

        def on_overflow() -> None:
            nonlocal overflowed
            overflowed = True
            _kill_group(proc)

        cap = limit * 4  # UTF-8 needs at most 4 bytes per character
        readers = [
            asyncio.create_task(_read_capped(stream, cap, on_overflow))
            for stream in (proc.stdout, proc.stderr)
        ]
        try:
            exited = await _wait_for_exit(proc, timeout)
        except asyncio.CancelledError:
            _kill_group(proc)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(proc.wait(), _READER_DRAIN_TIMEOUT_S)
            for reader in readers:
                reader.cancel()
            raise
        timed_out = not exited
        # Always kill the group: background children must not outlive the command.
        _kill_group(proc)
        done, pending = await asyncio.wait(
            [*readers, asyncio.ensure_future(proc.wait())], timeout=_READER_DRAIN_TIMEOUT_S
        )
        for task in pending:
            task.cancel()
        stdout, stderr = (
            reader.result() if reader in done and not reader.cancelled() else b""
            for reader in readers
        )

        stdout_text = _truncate(stdout.decode("utf-8", errors="replace"), limit)
        stderr_text = _truncate(stderr.decode("utf-8", errors="replace"), limit)
        if timed_out:
            note = f"命令超时（{timeout:g} 秒），已终止"
            return ShellCommandOutput(
                stdout=stdout_text,
                stderr=f"{stderr_text}\n{note}" if stderr_text else note,
                outcome=ShellCallOutcome(type="timeout"),
                command=command,
            ), True
        if overflowed:
            stderr_text += f"\n…（输出超过上限 {limit} 字符，命令已被终止）"
        output = ShellCommandOutput(
            stdout=stdout_text,
            stderr=stderr_text,
            outcome=ShellCallOutcome(type="exit", exit_code=proc.returncode),
            command=command,
        )
        return output, overflowed or proc.returncode != 0


# ---- business tools -----------------------------------------------------


def _sdk_output(result: ToolResult) -> str | list[ToolOutputText | ToolOutputImage]:
    if not result.images:
        return result.text
    return [ToolOutputText(text=result.text)] + [
        ToolOutputImage(image_url=f"data:{image.media_type};base64,{image.data_base64}")
        for image in result.images
    ]


def build_function_tool(
    spec: ToolSpec, tool_ctx: ToolContext, results: dict[str, ToolResult]
) -> FunctionTool:
    """业务 `ToolSpec` → `FunctionTool`。每次调用的 `ToolResult` 按 `call_id` 记进
    `results`，事件转换时直接取用（保留 `is_error` 和原始图片）。
    """

    async def on_invoke(context: SdkToolContext[Any], raw_args: str) -> Any:
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError as exc:
            result = ToolResult(text=f"参数不是合法的 JSON：{exc}", is_error=True)
        else:
            if isinstance(args, dict):
                result = await invoke_tool(spec, tool_ctx, args)
            else:
                result = ToolResult(text="参数必须是 JSON 对象", is_error=True)
        results[context.tool_call_id] = result
        return _sdk_output(result)

    schema = spec.input_model.model_json_schema()
    try:
        return FunctionTool(
            name=spec.name,
            description=spec.description,
            params_json_schema=schema,
            on_invoke_tool=on_invoke,
            strict_json_schema=True,
        )
    except UserError as exc:
        # Some Pydantic schemas cannot be made strict (e.g. open dicts); fall back to non-strict.
        logger.warning(
            "工具 %s 的参数 schema 无法转成 strict 模式，改用非 strict：%s", spec.name, exc
        )
        return FunctionTool(
            name=spec.name,
            description=spec.description,
            params_json_schema=schema,
            on_invoke_tool=on_invoke,
            strict_json_schema=False,
        )


# ---- turn state and event conversion -------------------------------------


@dataclass
class _Turn:
    profile: ModelProfileValue
    workdir: Path
    results: dict[str, ToolResult] = field(default_factory=dict)
    failed_calls: set[str] = field(default_factory=set)
    pending_usage: list[SdkUsage] = field(default_factory=list)

    @property
    def priced(self) -> bool:
        return self.profile.price_input is not None and self.profile.price_output is not None

    def drain_usage(self) -> list[events.AgentEvent]:
        drained, self.pending_usage = self.pending_usage, []
        return [
            events.Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=turn_cost(self.profile, usage.input_tokens, usage.output_tokens),
                auth="api_key",
                priced=self.priced,
            )
            for usage in drained
        ]


class _UsageHooks(RunHooks[Any]):
    def __init__(self, turn: _Turn) -> None:
        self._turn = turn

    async def on_llm_end(
        self, context: RunContextWrapper[Any], agent: Agent[Any], response: ModelResponse
    ) -> None:
        self._turn.pending_usage.append(response.usage)


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _parse_args(raw: Any) -> dict[str, object]:
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _patch_path(workdir: Path, raw: Any) -> object:
    """apply_patch 路径 → 规范化的工作区相对路径（与 editor 实际写入的一致）；
    不安全的路径原样保留（editor 会拒绝它，事件里保留模型给的原文便于排查）。"""
    if not isinstance(raw, str) or not raw:
        return raw
    try:
        return to_workspace_relpath(workdir, raw)
    except ScopeError:
        return raw


def _tool_call(item: ToolCallItem, workdir: Path) -> events.ToolCall:
    raw = item.raw_item
    kind = _get(raw, "type")
    call_id = item.call_id or ""
    if kind == "function_call":
        return events.ToolCall(call_id, str(_get(raw, "name")), _parse_args(_get(raw, "arguments")))
    if kind == "apply_patch_call":
        operation = _get(raw, "operation")
        args: dict[str, object] = {
            key: _get(operation, key)
            for key in ("type", "path", "move_to", "diff")
            if _get(operation, key)
        }
        for key in ("path", "move_to"):
            if key in args:
                args[key] = _patch_path(workdir, args[key])
        return events.ToolCall(call_id, "apply_patch", args)
    if kind == "shell_call":
        commands = _get(_get(raw, "action"), "commands") or []
        return events.ToolCall(call_id, "shell", {"commands": [str(c) for c in commands]})
    if kind == "web_search_call":
        action = _get(raw, "action")
        query = _get(action, "query")
        return events.ToolCall(call_id, "web_search", {"query": query} if query else {})
    return events.ToolCall(call_id, item.tool_name or str(kind or "unknown"), {})


def _tool_result(item: ToolCallOutputItem, turn: _Turn) -> events.ToolResult:
    call_id = item.call_id or ""
    business = turn.results.pop(call_id, None)
    if business is not None:
        return events.ToolResult(
            call_id=call_id,
            text=business.text,
            images=list(business.images),
            is_error=business.is_error,
        )
    failed = _get(item.raw_item, "status") == "failed" or call_id in turn.failed_calls
    output = item.output
    return events.ToolResult(
        call_id=call_id, text="" if output is None else str(output), is_error=failed
    )


def _convert(event: Any, turn: _Turn) -> list[events.AgentEvent]:
    if isinstance(event, RawResponsesStreamEvent):
        data = event.data
        if data.type == "response.output_text.delta":
            return [events.TextDelta(text=data.delta)]
        return []
    if not isinstance(event, RunItemStreamEvent):
        return []
    item = event.item
    if isinstance(item, MessageOutputItem):
        text = ItemHelpers.text_message_output(item)
        return [events.TextBlock(text=text)] if text else []
    if isinstance(item, ToolCallItem):
        call = _tool_call(item, turn.workdir)
        if call.name == "web_search":
            # Hosted tool: no separate output item; close the call so the UI does not hang.
            status = _get(item.raw_item, "status") or "completed"
            return [call, events.ToolResult(call_id=call.call_id, text=f"联网搜索：{status}")]
        return [call]
    if isinstance(item, ToolCallOutputItem):
        return [_tool_result(item, turn)]
    return []


# ---- session history -----------------------------------------------------


def _is_user_message(item: TResponseInputItem) -> bool:
    return isinstance(item, Mapping) and item.get("role") == "user"


def keep_recent_turns(
    turns: int,
) -> Callable[[list[TResponseInputItem], list[TResponseInputItem]], list[TResponseInputItem]]:
    """`session_input_callback`：历史从倒数第 `turns` 条用户消息开始截取。

    发给模型的是 **`turns` 轮历史 + 当前这一轮**（`turns=0` 只发当前轮）。按用户消息
    切分，保证不会从一对工具调用/结果的中间截断。
    """

    def combine(
        history: list[TResponseInputItem], new_items: list[TResponseInputItem]
    ) -> list[TResponseInputItem]:
        if turns <= 0:
            return list(new_items)
        starts = [index for index, item in enumerate(history) if _is_user_message(item)]
        if len(starts) > turns:
            history = history[starts[-turns] :]
        return list(history) + list(new_items)

    return combine


def _model_input(user_input: UserInput) -> str | list[TResponseInputItem]:
    if not user_input.images:
        return user_input.text
    content: list[dict[str, Any]] = [{"type": "input_text", "text": user_input.text}]
    content += [
        {
            "type": "input_image",
            "image_url": f"data:{image.media_type};base64,{image.data_base64}",
            "detail": "auto",
        }
        for image in user_input.images
    ]
    message: Any = {"role": "user", "content": content}
    return [message]


async def _cancel_on(token: CancelToken, result: RunResultStreaming) -> None:
    await token.wait()
    result.cancel()


# ---- runtime -------------------------------------------------------------


class OpenAIRuntime:
    def __init__(
        self,
        data_dir: Path,
        *,
        history_turns: int = 20,
        model_factory: ModelFactory = build_model,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._sessions_db = data_dir / SESSIONS_DB
        self._history_turns = history_turns
        self._model_factory = model_factory
        self._environ = environ if environ is not None else os.environ

    def _tools(self, ctx: TurnContext, turn: _Turn) -> list[Tool]:
        tool_ctx = ToolContext(
            project_id=ctx.project_id,
            stage=ctx.stage,
            workdir=ctx.workdir,
            record_tool_write=ctx.record_tool_write,
        )
        specs = list(ctx.tools)
        native: list[Tool] = []
        if ctx.model_profile.provider == "openai":
            native.append(
                ApplyPatchTool(editor=WorkspaceApplyPatchEditor(ctx.workdir, ctx.write_scope))
            )
            native.append(ShellTool(executor=LocalShellExecutor(ctx.workdir, turn.failed_calls)))
            if ctx.allow_web:
                native.append(WebSearchTool())
        else:
            specs += build_fallback_tools(ctx.write_scope)
        return [build_function_tool(spec, tool_ctx, turn.results) for spec in specs] + native

    def _setup(self, ctx: TurnContext) -> Model:
        profile = ctx.model_profile
        _check_provider(profile)
        if ctx.budget.max_cost_usd is not None and (
            profile.price_input is None or profile.price_output is None
        ):
            raise TurnSetupError(
                f"模型配置 {profile.name} 设置了成本上限但缺少输入/输出单价，无法执行成本预算"
            )
        return self._model_factory(profile, _api_key(profile, self._environ))

    async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
        session_id = ctx.resume_ref or uuid.uuid4().hex
        try:
            model = self._setup(ctx)
        except TurnSetupError as exc:
            yield events.TurnEnd(resume_ref=ctx.resume_ref, status="failed", error=str(exc))
            return

        turn = _Turn(profile=ctx.model_profile, workdir=ctx.workdir)
        agent = Agent(
            name="studio",
            instructions=ctx.system_prompt,
            model=model,
            model_settings=ModelSettings(include_usage=True),
            tools=self._tools(ctx, turn),
        )
        self._sessions_db.parent.mkdir(parents=True, exist_ok=True)
        session = SQLiteSession(session_id, self._sessions_db)
        result: RunResultStreaming | None = None
        watcher: asyncio.Task[None] | None = None
        error: str | None = None
        try:
            if not ctx.cancel_token.is_cancelled:
                result = Runner.run_streamed(
                    agent,
                    _model_input(ctx.user_input),
                    session=session,
                    hooks=_UsageHooks(turn),
                    max_turns=MAX_TURNS,
                    run_config=RunConfig(
                        tracing_disabled=True,
                        session_input_callback=keep_recent_turns(self._history_turns),
                    ),
                )
                watcher = asyncio.create_task(_cancel_on(ctx.cancel_token, result))
                async for event in result.stream_events():
                    for converted in turn.drain_usage() + _convert(event, turn):
                        yield converted
        except MaxTurnsExceeded:
            error = f"模型调用次数超过上限（{MAX_TURNS}）"
        except Exception as exc:
            logger.exception("OpenAI Agents SDK 调用失败")
            error = f"OpenAI Agents SDK 出错：{type(exc).__name__}: {exc}"
        finally:
            if watcher is not None:
                watcher.cancel()
            if result is not None and not result.is_complete:
                result.cancel()
            session.close()

        for usage in turn.drain_usage():
            yield usage
        if ctx.cancel_token.is_cancelled:
            yield events.TurnEnd(resume_ref=session_id, status="cancelled")
        elif error is not None:
            yield events.TurnEnd(resume_ref=session_id, status="failed", error=error)
        else:
            yield events.TurnEnd(resume_ref=session_id, status="done")


def register_openai(factory: RuntimeFactory, settings: Settings) -> None:
    """把 `openai` 运行时注册进 `factory`（控制者裁定 R2）；缺 key 在对应的 turn 里报 `failed`。"""
    data_dir = settings.data_dir
    history_turns = settings.openai_history_turns
    factory.register("openai", lambda: OpenAIRuntime(data_dir, history_turns=history_turns))
