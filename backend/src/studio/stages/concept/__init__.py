"""`concept` 阶段：动态图形短片与音乐 MV 的创意与要求（子项目 3 设计 §6.1，produce-stage 设计 §4）。

产物 `concept/brief.md`（固定八章，含「硬性要求」，见 `check_concept.SECTIONS`）；工具：联网搜索/
抓取、`check_concept`，以及 MV 用的 `analyze_music`（歌曲由用户在画布上传到 `music/source.*`，
分析结果写进 `music/`，都是工具托管文件）。定稿条件是 `check_concept` 没有错误，由用户确认；
这是流水线里唯一的人工确认点，后面的 `produce` 阶段由模型自己迭代。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.common import FETCH_URL_TOOL, WEB_SEARCH_TOOL
from studio.stages.common.music_source import SOURCE_EXTENSIONS
from studio.stages.common.score.analyze import ANALYZE_MUSIC_TOOL
from studio.stages.concept.check_concept import (
    CHECK_CONCEPT_TOOL,
    check_workspace,
    sections_for,
    workspace_lyrics,
)
from studio.timeline.lyrics import LyricsError
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(
    writable=["concept/brief.md"],
    tool_managed=[
        "music/analysis.json",
        "music/analysis.png",
        *(f"music/source.{ext}" for ext in SOURCE_EXTENSIONS),  # written by the upload endpoint
        "music/lyrics.lrc",  # written by the upload endpoint
    ],
)
_TOOLS: list[ToolSpec] = [WEB_SEARCH_TOOL, FETCH_URL_TOOL, CHECK_CONCEPT_TOOL, ANALYZE_MUSIC_TOOL]


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
        # File-level entries for the user-input files under `music/` (the uploaded song, its
        # lyrics and analysis): changing them and re-finalizing marks `produce` stale, while
        # `produce`'s own outputs in `music/` (music.wav, events.json, ...) do not.
        return [
            "concept",
            *(f"music/source.{ext}" for ext in SOURCE_EXTENSIONS),
            "music/analysis.json",
            "music/analysis.png",
            "music/lyrics.lrc",
        ]

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return check_workspace(workdir).errors

    def status_summary(self, workdir: Path) -> str:
        result = check_workspace(workdir)
        try:
            lyrics = workspace_lyrics(workdir)
        except LyricsError:
            lyrics = []
        total = len(sections_for(has_lyrics=bool(lyrics)))
        note = f"；歌词 {len(lyrics)} 句" if lyrics else ""
        return f"brief.md 已有 {result.found_sections}/{total} 个章节{note}"


STAGE = ConceptStage()
