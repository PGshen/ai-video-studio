"""运行时事件处理（设计 §4.4）：把 `AgentRuntime` 产出的事件落库、推送，并维护
`_State`（步数、成本、待发布的工作区改动）。

拆自 `runner.py`（TD-15）。这里的函数以 `runner: TurnRunner` 为第一个参数，通过它
调用 `TurnRunner` 的持久化/推送方法（`_persist`/`_publish`）和调度方法
（`_request_stop`）——这些仍然是 `TurnRunner` 的职责，事件处理只决定"发生了什么、
要不要发"。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from studio.agent import events
from studio.agent.turn_state import _Job, _State

if TYPE_CHECKING:
    from studio.agent.runner import TurnRunner

TOOL_RESULT_MAX_CHARS = 8000
"""落库的工具结果文本/工具参数字符串的上限；超出部分截断（设计 §3.1 说明）。"""


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text, False
    return text[:TOOL_RESULT_MAX_CHARS] + "…（已截断）", True


def _truncate_value(value: object) -> object:
    if isinstance(value, str):
        return _truncate(value)[0]
    if isinstance(value, dict):
        return {k: _truncate_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_value(v) for v in value]
    return value


def _truncate_args(args: dict[str, object]) -> dict[str, object]:
    return {k: _truncate_value(v) for k, v in args.items()}


def handle(runner: TurnRunner, job: _Job, state: _State, event: events.AgentEvent) -> None:
    if isinstance(event, events.TextDelta):
        runner._publish(job, "text_delta", {"text": event.text})
    elif isinstance(event, events.TextBlock):
        runner._persist(job, "text", {"text": event.text})
    elif isinstance(event, events.ToolCall):
        state.steps += 1
        state.calls[event.call_id] = event
        runner._persist(
            job,
            "tool_call",
            {"call_id": event.call_id, "name": event.name, "args": _truncate_args(event.args)},
        )
        limit = job.profile.max_steps_per_turn
        if limit is not None and state.steps > limit:
            _exceed_budget(runner, job, state, "steps")
    elif isinstance(event, events.ToolResult):
        text, truncated = _truncate(event.text)
        runner._persist(
            job,
            "tool_result",
            {
                "call_id": event.call_id,
                "text": text,
                "truncated": truncated,
                "is_error": event.is_error,
                # Image payloads are not persisted, only their types.
                "images": [{"media_type": image.media_type} for image in event.images],
            },
        )
        _after_tool_result(runner, job, state, event)
    elif isinstance(event, events.Usage):
        state.input_tokens += event.input_tokens
        state.output_tokens += event.output_tokens
        state.cost_usd += event.cost_usd
        # Subscription (login) auth: cost is informational, only steps are enforced.
        if event.auth == "login":
            state.cost_advisory = True
        if not event.priced and not state.cost_unpriced:
            state.cost_unpriced = True
            runner._persist(
                job, "notice", {"kind": "cost_unpriced", "message": "未配置单价，成本未统计"}
            )
        limit = job.profile.max_cost_per_turn
        if limit is not None and not state.cost_advisory and state.cost_usd > limit:
            _exceed_budget(runner, job, state, "cost")
    elif isinstance(event, events.TurnEnd):
        state.end = event


def _after_tool_result(
    runner: TurnRunner, job: _Job, state: _State, event: events.ToolResult
) -> None:
    call = state.calls.get(event.call_id)
    recorded, state.pending_tool_paths = state.pending_tool_paths, []
    if call is not None and call.name in events.FILE_TOOL_NAMES:
        # `move_to` is the target of an apply_patch rename (OpenAIRuntime);
        # `file_path`/`notebook_path` are Claude's native write tool args
        # (TD-13: Claude does not use `path`).
        candidates = (
            call.args.get("path"),
            call.args.get("file_path"),
            call.args.get("notebook_path"),
            call.args.get("move_to"),
        )
        # An empty list means "unknown paths, refetch" (e.g. shell commands).
        paths = [path for path in candidates if isinstance(path, str)]
        # Dedupe while preserving first-seen order (TD-8): a native tool's
        # own path can also show up in `recorded` via `record_tool_write`.
        merged = dict.fromkeys(paths + recorded)
        runner._publish(job, "workspace_changed", {"paths": list(merged)})
    elif recorded:
        runner._publish(job, "workspace_changed", {"paths": recorded})


def _exceed_budget(runner: TurnRunner, job: _Job, state: _State, kind: str) -> None:
    if state.budget_exceeded:
        return
    state.budget_exceeded = True
    runner._persist(job, "notice", {"kind": "budget_exceeded", "budget": kind})
    runner._request_stop(job)
