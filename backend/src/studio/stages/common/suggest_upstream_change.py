"""`suggest_upstream_change` 工具（设计 §5.3/§5.4）：向上游阶段提出回退建议。

`build_suggest_upstream_change_tool(engine)` 是一个工厂函数而不是模块级
`ToolSpec` 常量，因为 handler 要写 `suggestions` 表，需要一个 `Engine`；
`Engine` 通过闭包捆进 `ToolSpec.handler`，调用方（目前是各阶段的测试，
未来是 `main` 组装阶段时）只需要传一次 `engine`。

`stages={"animation"}`：先只给动画阶段用（本计划范围）；M3 的 narrative
agent 要复用同一个工具时，只需要在调用 `build_suggest_upstream_change_tool`
之后把返回的 `ToolSpec` 的 `stages` 换成 `{"animation", "narrative"}`（或者
在这里加一个 `stages` 参数），不用改这个文件的其它部分。
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import Engine

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.db.repo.suggestions import create_suggestion


class SuggestUpstreamChangeArgs(BaseModel):
    to_stage: str
    content: str


def build_suggest_upstream_change_tool(engine: Engine) -> ToolSpec:
    """构造绑定了 `engine` 的 `suggest_upstream_change` `ToolSpec`。"""

    def handler(ctx: ToolContext, args: SuggestUpstreamChangeArgs) -> ToolResult:
        create_suggestion(
            engine,
            project_id=ctx.project_id,
            from_stage=ctx.stage,
            to_stage=args.to_stage,
            content=args.content,
            turn_id=None,
        )
        return ToolResult(text="已记录回退建议，会在对话中提醒用户处理。")

    return ToolSpec(
        name="suggest_upstream_change",
        description="向上游阶段提出回退建议：记录一条待处理的建议，不直接修改上游产物。",
        input_model=SuggestUpstreamChangeArgs,
        stages={"animation"},
        handler=handler,
    )
