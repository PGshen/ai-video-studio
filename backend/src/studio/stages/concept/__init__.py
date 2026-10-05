"""`concept` 阶段：动态图形短片的创意简报（子项目 3 设计 §6.1）。

产物 `concept/brief.md`（固定七章，见 `check_concept.SECTIONS`）；工具：联网搜索/抓取与
`check_concept`。定稿条件是 `check_concept` 没有错误，由用户确认。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.common import FETCH_URL_TOOL, WEB_SEARCH_TOOL
from studio.stages.concept.check_concept import (
    CHECK_CONCEPT_TOOL,
    SECTIONS,
    check_workspace,
)
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(writable=["concept/brief.md"], tool_managed=[])
_TOOLS: list[ToolSpec] = [WEB_SEARCH_TOOL, FETCH_URL_TOOL, CHECK_CONCEPT_TOOL]


class ConceptStage:
    name = "concept"
    allow_web = True
    workspaceless = False

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def reads(self) -> list[str]:
        return []

    def prepare_turn(self, workdir: Path) -> None:
        return None

    def artifact_dirs(self) -> list[str]:
        return ["concept"]

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return check_workspace(workdir).errors

    def status_summary(self, workdir: Path) -> str:
        result = check_workspace(workdir)
        return f"brief.md 已有 {result.found_sections}/{len(SECTIONS)} 个章节"


STAGE = ConceptStage()
