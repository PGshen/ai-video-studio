"""`suggest_upstream_change` 工具（设计 §5.3/§5.4）：向上游阶段提出回退建议。

`Engine` 通过 `ToolContext.engine`（TD-32）传入 handler，不再需要工厂函数
把它闭包进 `ToolSpec.handler`——和 `validate_scenes`/`render_preview` 一样，
`SUGGEST_UPSTREAM_CHANGE_TOOL` 是模块加载时就能建好的常量，`AnimationStage.tools()`
直接放进列表即可。
"""

from __future__ import annotations

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.db.repo.suggestions import create_suggestion


class SuggestUpstreamChangeArgs(BaseModel):
    to_stage: str
    content: str


def _handler(ctx: ToolContext, args: SuggestUpstreamChangeArgs) -> ToolResult:
    if ctx.engine is None:
        return ToolResult(text="内部错误：当前上下文没有数据库连接。", is_error=True)
    create_suggestion(
        ctx.engine,
        project_id=ctx.project_id,
        from_stage=ctx.stage,
        to_stage=args.to_stage,
        content=args.content,
        turn_id=None,
    )
    return ToolResult(text="已记录回退建议，会在对话中提醒用户处理。")


SUGGEST_UPSTREAM_CHANGE_TOOL = ToolSpec(
    name="suggest_upstream_change",
    description="向上游阶段提出回退建议：记录一条待处理的建议，不直接修改上游产物。",
    input_model=SuggestUpstreamChangeArgs,
    stages={"animation"},
    handler=_handler,
)
