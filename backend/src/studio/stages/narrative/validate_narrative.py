"""`validate_narrative` 工具（设计 §5.2；计划 M3 T5）：校验 `narrative/narrative.json`。"""

from __future__ import annotations

import json

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.stages.narrative.schema import NarrativeValidationError, validate_and_normalize
from studio.workspace import files

_NARRATIVE_PATH = "narrative/narrative.json"


class ValidateNarrativeArgs(BaseModel):
    """`validate_narrative` 无入参：总是校验当前工作区里的 narrative.json。"""


async def _handler(ctx: ToolContext, args: ValidateNarrativeArgs) -> ToolResult:
    narrative_path = files.safe_path(ctx.workdir, _NARRATIVE_PATH)
    if not narrative_path.is_file():
        return ToolResult(text="还没有写 narrative/narrative.json。", is_error=True)

    raw_text = narrative_path.read_text(encoding="utf-8")
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return ToolResult(text=f"narrative.json 不是合法的 JSON：{exc}", is_error=True)

    try:
        narrative = validate_and_normalize(raw)
    except NarrativeValidationError as exc:
        return ToolResult(text="\n".join(exc.errors), is_error=True)

    return ToolResult(text=f"全部 {len(narrative.scenes)} 个镜头校验通过。")


VALIDATE_NARRATIVE_TOOL = ToolSpec(
    name="validate_narrative",
    description="校验 narrative.json：cue_text 是否覆盖 narration、transition 是否合法。",
    input_model=ValidateNarrativeArgs,
    stages={"narrative"},
    handler=_handler,
)
