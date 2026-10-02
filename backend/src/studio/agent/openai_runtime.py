"""OpenAI Agents SDK 适配器（设计 §4.1–§4.3；SDK 行为见 docs/references/openai-agents-sdk.md）。

按 `model_profile.provider` 选两条路径：

- `openai` → `OpenAIResponsesModel`（显式 `AsyncOpenAI(api_key, base_url)`），原生
  `ApplyPatchTool`（`WorkspaceApplyPatchEditor`，经 `workspace.files` 落盘）+
  `ShellTool`（`LocalShellExecutor`，工作目录为工作区，经 macOS `sandbox-exec` 拒读仓库根
  与 `data_dir`、只写工作区、无网络，见 `shell_sandbox`）；`ctx.allow_web` 时加托管
  `WebSearchTool`。`base_url` 不是官方 API（例如 OpenRouter）或本机没有 `sandbox-exec`
  （非 macOS）时不提供 Shell，改给兜底只读工具 `list_files`/`read_file`
  （`native_shell_supported`）。
- `litellm` → `LitellmModel`（显式传 `api_key`/`base_url`，不改 `os.environ`），
  兜底文件工具（`fallback_tools`），不提供 Shell，M1 不提供联网工具（Tavily 在 M4）。

两条路径的业务 `ToolSpec` 都转成 `FunctionTool`，调用走 `invoke_tool`；`model_profile.
supports_vision` 为真时图片结果转成 `ToolOutputImage`（data URL），为假时（R2，
docs/references/openai-agents-sdk.md）只发文本、注明"模型不支持图片"（`_sdk_output`）。

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
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agents import (
    Agent,
    ApplyPatchTool,
    MaxTurnsExceeded,
    Model,
    ModelResponse,
    ModelSettings,
    OpenAIResponsesModel,
    RunConfig,
    RunContextWrapper,
    RunHooks,
    Runner,
    RunResultStreaming,
    ShellTool,
    SQLiteSession,
    Tool,
    TResponseInputItem,
    WebSearchTool,
)
from openai import AsyncOpenAI
from openai.types.shared import Reasoning

from studio.agent import events
from studio.agent.apply_patch import WorkspaceApplyPatchEditor
from studio.agent.fallback_tools import build_fallback_tools
from studio.agent.openai_tools import _Turn, build_function_tool, convert
from studio.agent.runtime import (
    Budget,
    CancelToken,
    Effort,
    RuntimeFactory,
    TurnContext,
    UserInput,
)
from studio.agent.sandbox_paths import sensitive_home_dirs
from studio.agent.shell import LocalShellExecutor
from studio.agent.shell_sandbox import sandbox_available as _sandbox_available
from studio.config import Settings
from studio.config import repo_root as _repo_root
from studio.db.repo.profiles import ModelProfileValue

logger = logging.getLogger(__name__)

SESSIONS_DB = "openai_sessions.db"
MAX_TURNS = 200
"""不限步数时 SDK 的 `max_turns`（模型调用次数上限）；SDK 默认 10 太小。"""


def max_turns(budget: Budget) -> int:
    """SDK `max_turns` 的宽松兜底（TD-18）。

    真正的步数预算由 TurnRunner 按 `max_steps_per_turn` 计数并用取消令牌强制；
    这里只防失控。一次模型调用至少产出一个工具调用才会有下一次调用，runner 在第
    `max_steps + 1` 个工具调用时就停下，所以 `max_steps * 2 + 2` 在正常情况下
    永远不会先于 runner 触发。
    """
    if budget.max_steps is None:
        return MAX_TURNS
    return budget.max_steps * 2 + 2


ModelFactory = Callable[[ModelProfileValue, str], Model]


class TurnSetupError(Exception):
    """本轮无法开始（缺 key、未知 provider、缺单价）；错误信息直接进 `TurnEnd.error`。"""


def openai_client(profile: ModelProfileValue, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, base_url=profile.base_url)


SUPPORTED_PROVIDERS = ("openai", "litellm")

OFFICIAL_OPENAI_HOST = "api.openai.com"
FALLBACK_READ_TOOLS = frozenset({"list_files", "read_file"})
"""网关（非 `api.openai.com`）上代替 Shell 的兜底只读工具；写入仍走原生 `apply_patch`。"""


def native_shell_supported(
    profile: ModelProfileValue, *, sandbox_available: Callable[[], bool] = _sandbox_available
) -> bool:
    """`provider=openai` 的配置能否用本地执行的原生 `ShellTool`。

    本机必须能用 `sandbox-exec` 包裹 Shell（macOS，TD-20）；否则失败关闭、不提供 Shell。
    此外只有官方 API（`base_url` 为空或主机是 `api.openai.com`）支持：OpenRouter 的
    Responses API 对 `shell` 没有客户端执行模式，`local` 环境不受支持，命令会进它的
    托管沙箱，看不到工作区（F2，2026-09-28 核实，见 docs/references/openai-agents-sdk.md）。
    其他网关按同样保守处理。
    """
    return sandbox_available() and is_official_openai(profile)


def is_official_openai(profile: ModelProfileValue) -> bool:
    """`base_url` 为空或主机正好是 `api.openai.com`。"""
    if not profile.base_url:
        return True
    return (urlsplit(profile.base_url).hostname or "").lower() == OFFICIAL_OPENAI_HOST


def _check_provider(profile: ModelProfileValue) -> None:
    if profile.provider not in SUPPORTED_PROVIDERS:
        raise TurnSetupError(
            f"OpenAI 运行时不支持 provider={profile.provider}（只支持 openai、litellm）"
        )


_REASONING_SUMMARY = Reasoning(summary="auto")
_REASONING_MODEL = re.compile(r"^(o\d|gpt-[5-9])", re.IGNORECASE)
"""Best effort: reasoning models return a summary (shown as thinking), others return none."""


def _reasoning(effort: Effort | None) -> Reasoning:
    return Reasoning(summary="auto", effort=effort) if effort else _REASONING_SUMMARY


def model_settings(profile: ModelProfileValue, effort: Effort | None = None) -> ModelSettings:
    """每轮的 `ModelSettings`。

    `provider=openai` 且走网关（非官方主机，例如 OpenRouter）时：OpenRouter 的 Responses
    API 无状态、不保存任何条目，回放的 `reasoning` 条目只带 id 会报 "Item not found"，
    所以显式 `store=False` 并请求 `reasoning.encrypted_content`，让会话里存下的
    reasoning 条目自带内容（F2 审查，2026-09-28）。
    """
    if profile.provider == "openai" and not is_official_openai(profile):
        return ModelSettings(
            include_usage=True,
            store=False,
            response_include=["reasoning.encrypted_content"],
            reasoning=_reasoning(effort),
        )
    if profile.provider == "openai":
        # api.openai.com rejects `reasoning` for non-reasoning models, which would fail every turn,
        # while an unrequested summary only costs the thinking display; so only ask when the model
        # name says it reasons. (Gateways above are lenient, verified on OpenRouter.)
        if _REASONING_MODEL.match(profile.model):
            return ModelSettings(include_usage=True, reasoning=_reasoning(effort))
        return ModelSettings(include_usage=True)
    # LiteLLM (chat completions): the SDK ignores `reasoning.summary` here and warns on
    # every call, so leave it unset; provider-returned reasoning still streams through.
    return ModelSettings(include_usage=True)


def build_model(profile: ModelProfileValue, api_key: str) -> Model:
    _check_provider(profile)
    if profile.provider == "openai":
        return OpenAIResponsesModel(
            model=profile.model, openai_client=openai_client(profile, api_key)
        )
    # Imported lazily: importing litellm takes seconds and is only needed on this path.
    from agents.extensions.models.litellm_model import LitellmModel

    return LitellmModel(model=profile.model, base_url=profile.base_url, api_key=api_key)


def _api_key(profile: ModelProfileValue, environ: Mapping[str, str]) -> str:
    if not profile.api_key_env:
        raise TurnSetupError(
            f"模型配置 {profile.name} 没有设置 api_key_env，OpenAI 运行时需要 API key"
        )
    key = environ.get(profile.api_key_env)
    if not key:
        raise TurnSetupError(f"环境变量 {profile.api_key_env} 未设置，无法调用模型 {profile.name}")
    return key


class _UsageHooks(RunHooks[Any]):
    def __init__(self, turn: _Turn) -> None:
        self._turn = turn

    async def on_llm_end(
        self, context: RunContextWrapper[Any], agent: Agent[Any], response: ModelResponse
    ) -> None:
        self._turn.pending_usage.append(response.usage)


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
        repo_root: Path | None = None,
        sandbox_available: Callable[[], bool] = _sandbox_available,
    ) -> None:
        self._sessions_db = data_dir / SESSIONS_DB
        # Shell sandbox deny-read list, same policy as the Claude Bash sandbox (TD-1/TD-20).
        self._shell_deny_read = [
            repo_root if repo_root is not None else _repo_root(),
            data_dir,
            *sensitive_home_dirs(),  # TD-27
        ]
        self._sandbox_available = sandbox_available
        self._history_turns = history_turns
        self._model_factory = model_factory
        self._environ = environ if environ is not None else os.environ

    def _tools(self, ctx: TurnContext, turn: _Turn) -> list[Tool]:
        tool_ctx = ctx.tool_context()
        specs = list(ctx.tools)
        native: list[Tool] = []
        if ctx.model_profile.provider == "openai":
            native.append(
                ApplyPatchTool(editor=WorkspaceApplyPatchEditor(ctx.workdir, ctx.write_scope))
            )
            if native_shell_supported(ctx.model_profile, sandbox_available=self._sandbox_available):
                executor = LocalShellExecutor(
                    ctx.workdir,
                    turn.failed_calls,
                    environ=self._environ,
                    deny_read=self._shell_deny_read,
                )
                native.append(ShellTool(executor=executor))
            else:
                specs += [
                    spec
                    for spec in build_fallback_tools(ctx.write_scope)
                    if spec.name in FALLBACK_READ_TOOLS
                ]
            if ctx.allow_web:
                native.append(WebSearchTool())
        else:
            specs += build_fallback_tools(ctx.write_scope)
        return [
            build_function_tool(
                spec, tool_ctx, turn.results, supports_vision=ctx.model_profile.supports_vision
            )
            for spec in specs
        ] + native

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
            model_settings=model_settings(ctx.model_profile, ctx.effort),
            tools=self._tools(ctx, turn),
        )
        self._sessions_db.parent.mkdir(parents=True, exist_ok=True)
        session = SQLiteSession(session_id, self._sessions_db)
        result: RunResultStreaming | None = None
        watcher: asyncio.Task[None] | None = None
        error: str | None = None
        turn_limit = max_turns(ctx.budget)
        try:
            if not ctx.cancel_token.is_cancelled:
                result = Runner.run_streamed(
                    agent,
                    _model_input(ctx.user_input),
                    session=session,
                    hooks=_UsageHooks(turn),
                    max_turns=turn_limit,
                    run_config=RunConfig(
                        tracing_disabled=True,
                        session_input_callback=keep_recent_turns(self._history_turns),
                    ),
                )
                watcher = asyncio.create_task(_cancel_on(ctx.cancel_token, result))
                async for event in result.stream_events():
                    for converted in turn.drain_usage() + convert(event, turn):
                        yield converted
        except MaxTurnsExceeded:
            error = f"模型调用次数超过上限（{turn_limit}）"
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
