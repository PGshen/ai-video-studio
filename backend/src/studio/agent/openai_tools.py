"""业务 `ToolSpec` ↔ OpenAI Agents SDK `FunctionTool` 的桥接，以及 SDK item → `events.AgentEvent`
的转换（TD-16 从 `openai_runtime.py` 拆出）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents import (
    FunctionTool,
    ItemHelpers,
    MessageOutputItem,
    RawResponsesStreamEvent,
    ReasoningItem,
    RunItemStreamEvent,
    ToolCallItem,
    ToolCallOutputItem,
    ToolOutputImage,
    ToolOutputText,
    UserError,
)
from agents.tool_context import ToolContext as SdkToolContext
from agents.usage import Usage as SdkUsage

from studio.agent import events
from studio.agent.apply_patch import to_workspace_relpath
from studio.agent.tools import ToolContext, ToolResult, ToolSpec, invoke_tool
from studio.db.repo.profiles import ModelProfileValue
from studio.workspace.files import ScopeError

logger = logging.getLogger(__name__)


# ---- turn state (shared between tool invocation, usage hooks and event conversion) --------


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


def turn_cost(profile: ModelProfileValue, input_tokens: int, output_tokens: int) -> float:
    """按模型配置单价（美元 / 百万 token）计算成本；缺单价的一侧按 0 计。

    缓存命中的输入 token 也按普通输入价计（宁可高估，和旧项目的做法一致）。
    """
    price_in = profile.price_input or 0.0
    price_out = profile.price_output or 0.0
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


# ---- business tools -----------------------------------------------------


def _sdk_output(
    result: ToolResult, *, supports_vision: bool
) -> str | list[ToolOutputText | ToolOutputImage]:
    if not result.images or not supports_vision:
        if result.images and not supports_vision:
            # R2（LiteLLM/非视觉模型，docs/references/openai-agents-sdk.md）：模型看不懂
            # 图片输入，发了也只会让模型编造颜色；只保留文本指标并注明原因。
            return f"{result.text}\n（模型不支持图片，已省略图片内容）"
        return result.text
    return [ToolOutputText(text=result.text)] + [
        ToolOutputImage(image_url=f"data:{image.media_type};base64,{image.data_base64}")
        for image in result.images
    ]


def build_function_tool(
    spec: ToolSpec,
    tool_ctx: ToolContext,
    results: dict[str, ToolResult],
    *,
    supports_vision: bool = True,
) -> FunctionTool:
    """业务 `ToolSpec` → `FunctionTool`。每次调用的 `ToolResult` 按 `call_id` 记进
    `results`，事件转换时直接取用（保留 `is_error` 和原始图片）。`supports_vision`
    为 `False`（模型配置 `supports_vision=false`）时，发给模型的工具输出不带图片，
    只保留文本（`_sdk_output`）；`results` 里仍保留原始 `ToolResult.images`，供事件/
    画布使用。
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
        return _sdk_output(result, supports_vision=supports_vision)

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


# ---- item -> event conversion -------------------------------------------


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


def convert(event: Any, turn: _Turn) -> list[events.AgentEvent]:
    if isinstance(event, RawResponsesStreamEvent):
        data = event.data
        if data.type == "response.output_text.delta":
            return [events.TextDelta(text=data.delta)]
        if data.type == "response.reasoning_summary_text.delta" and data.delta.strip():
            return [events.ThinkingDelta(text=data.delta)]
        return []
    if not isinstance(event, RunItemStreamEvent):
        return []
    item = event.item
    if isinstance(item, MessageOutputItem):
        text = ItemHelpers.text_message_output(item)
        return [events.TextBlock(text=text)] if text else []
    if isinstance(item, ReasoningItem):
        parts = [str(_get(part, "text") or "") for part in _get(item.raw_item, "summary") or []]
        text = "\n".join(part for part in parts if part.strip())
        return [events.ThinkingBlock(text=text)] if text else []
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
