"""叙事阶段占位定义（设计 §4.3、§5.2）。

M1 只提供占位提示词和 §4.3 的可写范围（`narrative/narrative.json` 可写，
`narrative/timing.json` 只能由工具写）；`validate_narrative`、
`synthesize_tts` 等业务工具在实现叙事阶段业务逻辑时补充。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.workspace import files
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(
    writable=["narrative/narrative.json"], tool_managed=["narrative/timing.json"]
)


class NarrativeStage:
    name = "narrative"

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return []

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def upstream_stages(self) -> list[str]:
        return ["topic"]

    def artifact_dirs(self) -> list[str]:
        return ["narrative"]

    def status_summary(self, workdir: Path) -> str:
        count = sum(1 for path in files.list_tree(workdir) if path.startswith("narrative/"))
        return f"narrative/ 下有 {count} 个文件"


STAGE = NarrativeStage()
