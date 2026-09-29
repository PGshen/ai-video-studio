"""`check_brief` 工具（设计 §5.1；计划 M4 T6）：检查 `topic/brief.md` 的结构。"""

from __future__ import annotations

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.stages.topic.brief import check_workspace


class CheckBriefArgs(BaseModel):
    pass


def format_check(result_errors: list[str], result_warnings: list[str]) -> str:
    lines: list[str] = []
    if result_errors:
        lines.append(f"简报结构检查没有通过（{len(result_errors)} 个错误）：")
        lines += [f"- {e}" for e in result_errors]
    else:
        lines.append("简报结构检查通过。")
    if result_warnings:
        lines.append(f"警告（{len(result_warnings)} 条，不阻止定稿）：")
        lines += [f"- {w}" for w in result_warnings]
    return "\n".join(lines)


def _handler(ctx: ToolContext, args: CheckBriefArgs) -> ToolResult:
    result = check_workspace(ctx.workdir)
    return ToolResult(text=format_check(result.errors, result.warnings), is_error=not result.ok)


CHECK_BRIEF_TOOL = ToolSpec(
    name="check_brief",
    description=(
        "检查 topic/brief.md 的结构：七个章节是否齐全、关键事实是否都带出处和把握程度。"
        "写完或改完简报后调用，错误全部修完再交给用户定稿。"
    ),
    input_model=CheckBriefArgs,
    stages={"topic"},
    handler=_handler,
)
