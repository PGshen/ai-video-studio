"""叙事阶段定义（设计 §4.3、§5.2）。

可写范围：`narrative/narrative.json` 由 agent 写，`narrative/timing.json`
和 `narrative/audio/**` 只能由 `synthesize_tts` 工具写。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.common import SUGGEST_UPSTREAM_CHANGE_TOOL
from studio.stages.narrative.synthesize_tts import SYNTHESIZE_TTS_TOOL
from studio.stages.narrative.validate_narrative import VALIDATE_NARRATIVE_TOOL
from studio.workspace import files
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(
    writable=["narrative/narrative.json"],
    tool_managed=["narrative/timing.json", "narrative/audio/**"],
)
_TOOLS: list[ToolSpec] = [
    VALIDATE_NARRATIVE_TOOL,
    SYNTHESIZE_TTS_TOOL,
    SUGGEST_UPSTREAM_CHANGE_TOOL,
]


class NarrativeStage:
    name = "narrative"
    allow_web = False
    workspaceless = False

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def upstream_stages(self) -> list[str]:
        return ["topic"]

    def artifact_dirs(self) -> list[str]:
        return ["narrative"]

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []

    def status_summary(self, workdir: Path) -> str:
        count = sum(1 for path in files.list_tree(workdir) if path.startswith("narrative/"))
        return f"narrative/ 下有 {count} 个文件"


STAGE = NarrativeStage()
