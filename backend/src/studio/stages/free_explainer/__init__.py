"""`free_explainer` 阶段：自由讲解的单阶段（free-mode 设计 §4）。

没有选题与上游：用户在对话里直接给题目，叙事、配音、场景（以及可选的背景乐）都在这一个阶段完成。
时间轴由工具即时从工作区顶层的叙事与配音构建（`stages.common.timeline_source`）。整个工作区可写，
联网。定稿只在「成片定稿」时发生，没有额外的定稿条件（计划决策 D1）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.common import FETCH_URL_TOOL, WEB_SEARCH_TOOL
from studio.stages.common.free_scope import free_write_scope
from studio.stages.common.narration import SYNTHESIZE_TTS_TOOL, VALIDATE_NARRATIVE_TOOL
from studio.stages.common.prompts import compose_prompt, fragment
from studio.stages.common.scenes import CANVAS_EXEMPLAR, WEBGL_EXEMPLAR
from studio.stages.common.scenes.render_preview_html import RENDER_PREVIEW_HTML_TOOL
from studio.stages.common.scenes.validate_scenes_html import VALIDATE_SCENES_HTML_TOOL
from studio.stages.common.score import AUDIO_EXEMPLAR
from studio.stages.common.score.tool import RENDER_MUSIC_TOOL
from studio.stages.free_explainer.status import status_summary
from studio.workspace.scope import WriteScope

_HERE = Path(__file__).parent
_PROMPT_PARTS = [
    _HERE / "opening.md",
    fragment("free-mode"),
    _HERE / "inputs.md",
    fragment("narration-schema"),
    fragment("narration-writing"),
    _HERE / "voice.md",
    fragment("scenes-explainer"),
    _HERE / "workflow.md",
    fragment("music-explainer"),
]
_WRITE_SCOPE = free_write_scope(["narrative/timing.json", "narrative/audio/*"])
_TOOLS: list[ToolSpec] = [
    WEB_SEARCH_TOOL,
    FETCH_URL_TOOL,
    VALIDATE_NARRATIVE_TOOL,
    SYNTHESIZE_TTS_TOOL,
    RENDER_MUSIC_TOOL,
    VALIDATE_SCENES_HTML_TOOL,
    RENDER_PREVIEW_HTML_TOOL,
]


class FreeExplainerStage:
    name = "free_explainer"
    allow_web = True
    workspaceless = False
    exec_network = False

    def system_prompt(self) -> str:
        return compose_prompt(*_PROMPT_PARTS)

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def reads(self) -> list[str]:
        return []

    def prepare_turn(self, workdir: Path) -> None:
        exemplars = workdir / "upstream" / "exemplar"
        exemplars.mkdir(parents=True, exist_ok=True)
        sources = [CANVAS_EXEMPLAR, WEBGL_EXEMPLAR]
        if (workdir / "music" / "compose.py").is_file():
            sources.append(AUDIO_EXEMPLAR)
        for source in sources:
            shutil.copyfile(source, exemplars / source.name)

    def artifact_dirs(self) -> list[str]:
        return ["narrative", "music", "animation"]

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []

    def status_summary(self, workdir: Path) -> str:
        return status_summary(workdir)


STAGE = FreeExplainerStage()
