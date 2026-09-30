"""`suggest_upstream_change` 工具（设计 §5.3/§5.4；计划 M5 T9，决策 D4）：向上游阶段提出回退建议。

`Engine` 通过 `ToolContext.engine`（TD-32）传入 handler，不再需要工厂函数把它闭包进
`ToolSpec.handler`——和 `validate_scenes`/`render_preview` 一样，`SUGGEST_UPSTREAM_CHANGE_TOOL`
是模块加载时就能建好的常量，`AnimationStage.tools()` 和 `NarrativeStage.tools()` 直接放进列表即可。

M5 T9：只允许向**直接上游**提（动画 → 叙事，叙事 → 选题；`ToolContext.upstream_stages`），
理由是直接上游的产物就是本阶段的输入，建议才有明确的处理对象；内容去空白后不能为空、
不超过 `MAX_CONTENT_CHARS`；记录产生它的 `turn_id`。成功后 TurnRunner 会给会话发一条
`suggestion` 事件（`agent/turn_events.py`）。
"""

from __future__ import annotations

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.db.repo.suggestions import create_suggestion

MAX_CONTENT_CHARS = 2000


class SuggestUpstreamChangeArgs(BaseModel):
    to_stage: str
    content: str


def _error(text: str) -> ToolResult:
    return ToolResult(text=text, is_error=True)


def _handler(ctx: ToolContext, args: SuggestUpstreamChangeArgs) -> ToolResult:
    if ctx.engine is None:
        return _error("内部错误：当前上下文没有数据库连接。")
    to_stage = args.to_stage.strip()
    if not ctx.upstream_stages:
        return _error(f"{ctx.stage} 阶段没有上游，不能提回退建议。")
    if to_stage not in ctx.upstream_stages:
        allowed = "、".join(ctx.upstream_stages)
        return _error(
            f"to_stage 只能填本阶段的直接上游：{allowed}（收到 {args.to_stage!r}）。"
            "更早的阶段请在回复里告诉用户，由用户决定。"
        )
    content = args.content.strip()
    if not content:
        return _error("建议内容不能为空：写清楚是哪个镜头/哪一段、什么问题、希望怎么改。")
    if len(content) > MAX_CONTENT_CHARS:
        return _error(
            f"建议内容太长（{len(content)} 字，上限 {MAX_CONTENT_CHARS}），请精简后重试。"
        )
    create_suggestion(
        ctx.engine,
        project_id=ctx.require_project(),
        from_stage=ctx.stage,
        to_stage=to_stage,
        content=content,
        turn_id=ctx.turn_id,
    )
    return ToolResult(text="已记录回退建议，会在对话中提醒用户处理。")


SUGGEST_UPSTREAM_CHANGE_TOOL = ToolSpec(
    name="suggest_upstream_change",
    description=(
        "向上游阶段提出回退建议：记录一条待处理的建议，不直接修改上游产物。"
        "to_stage 只能是本阶段的直接上游（动画阶段填 narrative，叙事阶段填 topic）。"
    ),
    input_model=SuggestUpstreamChangeArgs,
    stages={"animation", "narrative"},
    handler=_handler,
)
