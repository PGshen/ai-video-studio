"""运行时事件处理（设计 §4.4）：把 `AgentRuntime` 产出的事件落库、推送，并维护
`_State`（步数、成本、待发布的工作区改动）。

拆自 `runner.py`（TD-15）。这里的函数以 `runner: TurnRunner` 为第一个参数，通过它
调用 `TurnRunner` 的持久化/推送方法（`_persist`/`_publish`）和调度方法
（`_request_stop`）——这些仍然是 `TurnRunner` 的职责，事件处理只决定"发生了什么、
要不要发"。
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from studio.agent import events
from studio.agent.turn_state import _Job, _State
from studio.db.repo import suggestions as suggestions_repo
from studio.db.repo import turns as turns_repo

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


def _persist_image(runner: TurnRunner, image: events.ImageData) -> dict[str, str]:
    sha256 = runner._blobs.put(base64.b64decode(image.data_base64))
    return {"media_type": image.media_type, "sha256": sha256}


MODEL_SWITCHED_NOTICE = "model_switched"
"""会话换了模型之后的第一轮开头推的 `notice` 的 `kind`（M5 T7）。"""


def note_model_switch(runner: TurnRunner, job: _Job) -> None:
    """本轮用的模型配置和会话上一轮实际用的不同时，发一条 `notice`（落库、可回放）。

    上一轮用什么以 `turns.usage.profile_name` 为准（不是"会话当前配置被改过几次"），所以
    连续换两次、又换回原来那个，不会提示。找不到上一轮的记录（第一轮、M5 之前的旧 turn）
    也不提示。
    """
    previous = turns_repo.previous_run_profile_name(runner._engine, job.session.id, job.turn_id)
    if previous is None or previous == job.profile.name:
        return
    runner._persist(
        job,
        "notice",
        {
            "kind": MODEL_SWITCHED_NOTICE,
            "from": previous,
            "to": job.profile.name,
            "message": f"模型已从 {previous} 换为 {job.profile.name}（{job.profile.model}）",
        },
    )


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
                # TD-21: image bytes go into the content-addressed blob
                # store (same as workspace files); only the sha256 back
                # reference is persisted here, served on demand by
                # `GET /projects/{id}/blobs/{sha256}` (design §3.3).
                "images": [_persist_image(runner, image) for image in event.images],
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
        if event.includes_carryover and not state.cost_carryover:
            state.cost_carryover = True
            runner._persist(
                job,
                "notice",
                {"kind": "cost_carryover", "message": "本轮成本含上一轮被中断时的残余花费"},
            )
        # TD-25: the carryover amount cannot be separated from this turn's own cost, so a
        # turn that includes it is not judged against the budget (better to miss than to
        # end a turn that was within budget).
        limit = job.profile.max_cost_per_turn
        if (
            limit is not None
            and not state.cost_advisory
            and not state.cost_carryover
            and state.cost_usd > limit
        ):
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
    if call is not None and call.name == SUGGEST_TOOL_NAME and not event.is_error:
        _announce_suggestions(runner, job, state)


SUGGEST_TOOL_NAME = "suggest_upstream_change"
"""业务工具名（Claude 侧的 `mcp__studio__` 前缀已在适配层去掉）。"""


def _announce_suggestions(runner: TurnRunner, job: _Job, state: _State) -> None:
    """`suggest_upstream_change` 成功后，给本轮里还没发过事件的建议各发一条 `suggestion` 事件
    （M5 T9）。工具本身写库、拿不到总线，所以由这里按 `turn_id` 查回来；三个运行时都一样。"""
    for suggestion in suggestions_repo.list_turn_suggestions(runner._engine, job.turn_id):
        if suggestion.id in state.announced_suggestions:
            continue
        state.announced_suggestions.add(suggestion.id)
        runner._persist(
            job,
            "suggestion",
            {
                "suggestion_id": suggestion.id,
                "from_stage": suggestion.from_stage,
                "to_stage": suggestion.to_stage,
                "content": suggestion.content,
                "status": suggestion.status,
            },
        )


def _exceed_budget(runner: TurnRunner, job: _Job, state: _State, kind: str) -> None:
    if state.budget_exceeded:
        return
    state.budget_exceeded = True
    runner._persist(job, "notice", {"kind": "budget_exceeded", "budget": kind})
    runner._request_stop(job)
