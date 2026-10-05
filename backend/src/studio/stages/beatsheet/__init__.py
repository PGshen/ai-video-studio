"""`beatsheet` 阶段：动态图形短片的节拍脚本（子项目 3 设计 §6.2）。

产物 `beatsheet/beatsheet.json`（BPM、按小节数计的段落、每段的画面时刻 `moments`）；工具：
`validate_beatsheet` 与 `suggest_upstream_change`。定稿条件是校验没有错误。配乐按这里的网格产出，
时间轴的段落时长 = `bars × 4 × 60 / bpm`。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.beatsheet.validate_beatsheet import VALIDATE_BEATSHEET_TOOL, check_workspace
from studio.stages.common import SUGGEST_UPSTREAM_CHANGE_TOOL
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(writable=["beatsheet/beatsheet.json"], tool_managed=[])
_TOOLS: list[ToolSpec] = [VALIDATE_BEATSHEET_TOOL, SUGGEST_UPSTREAM_CHANGE_TOOL]


class BeatsheetStage:
    name = "beatsheet"
    allow_web = False
    workspaceless = False

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def reads(self) -> list[str]:
        # 音乐 MV（子项目 4）里 music 排在 beatsheet 之前；短片里 `upstream_of` 只会得到 concept。
        return ["concept", "music"]

    def prepare_turn(self, workdir: Path) -> None:
        return None

    def artifact_dirs(self) -> list[str]:
        return ["beatsheet"]

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return check_workspace(workdir).errors

    def status_summary(self, workdir: Path) -> str:
        result = check_workspace(workdir)
        if result.bpm is None or result.total_seconds is None:
            return f"节拍脚本校验有 {len(result.errors)} 个错误"
        return (
            f"{result.section_count} 个段落，BPM {result.bpm:g}，"
            f"总时长 {result.total_seconds:.2f} 秒"
        )


STAGE = BeatsheetStage()
