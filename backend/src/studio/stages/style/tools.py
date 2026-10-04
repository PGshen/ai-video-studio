"""`validate_style` 工具：检查草稿目录能不能保存（ADR 0019；计划 style-library T9）。"""

from __future__ import annotations

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.styles.store import validate_tree


class ValidateStyleArgs(BaseModel):
    pass


def _handler(ctx: ToolContext, args: ValidateStyleArgs) -> ToolResult:
    errors = validate_tree(ctx.workdir)
    if not errors:
        return ToolResult(text="风格检查通过：草稿可以保存。")
    lines = [f"风格检查没有通过（{len(errors)} 个问题）："]
    lines += [f"- {e}" for e in errors]
    return ToolResult(text="\n".join(lines), is_error=True)


VALIDATE_STYLE_TOOL = ToolSpec(
    name="validate_style",
    description=(
        "检查当前这套风格的草稿能不能保存：STYLE.md 的 frontmatter（name、description）、文件名和"
        "扩展名、.json 是否合法、入口里引用的文件是否都存在、有没有多余或不允许的文件。"
        "改完之后调用，把所有问题改完。名称是否与别的风格重复不在这里检查，保存时才会检查。"
    ),
    input_model=ValidateStyleArgs,
    stages={"style"},
    handler=_handler,
)
