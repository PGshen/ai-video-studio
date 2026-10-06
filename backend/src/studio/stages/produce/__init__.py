"""`produce` 阶段：配乐与动画合并，由模型自己决定节拍、镜头划分和对齐方式（produce-stage 设计）。

短片：写合成脚本 `music/compose.py`，`render_music` 渲染；MV：用户上传的歌曲由 `analyze_music`
分析，可选写截取区间 `music/range.json`。两种形态都自己写镜头划分 `animation/shots.json` 和
`animation/scenes/<镜头 id>.js`。上游只有 `concept/brief.md`。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.common import SUGGEST_UPSTREAM_CHANGE_TOOL
from studio.stages.common.music_source import SOURCE_EXTENSIONS
from studio.stages.common.scenes.render_preview_html import RENDER_PREVIEW_HTML_TOOL
from studio.stages.common.scenes.validate_scenes_html import VALIDATE_SCENES_HTML_TOOL
from studio.stages.common.score.analyze import ANALYZE_MUSIC_TOOL
from studio.stages.common.score.tool import RENDER_MUSIC_TOOL
from studio.stages.produce.blockers import finalize_blockers, status_summary
from studio.stages.produce.prepare import prepare_turn
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(
    writable=[
        "music/compose.py",
        "music/range.json",
        "animation/shots.json",
        "animation/scenes/*.js",
        "animation/lib/*.js",
        "animation/global.js",
        "animation/assets/*",
    ],
    tool_managed=[
        "music/music.wav",
        "music/events.json",
        "music/analysis.json",
        "music/analysis.png",
        "music/render.json",
        *(f"music/source.{ext}" for ext in SOURCE_EXTENSIONS),  # written by the upload endpoint
    ],
)
_TOOLS: list[ToolSpec] = [
    RENDER_MUSIC_TOOL,
    ANALYZE_MUSIC_TOOL,
    VALIDATE_SCENES_HTML_TOOL,
    RENDER_PREVIEW_HTML_TOOL,
    SUGGEST_UPSTREAM_CHANGE_TOOL,
]


class ProduceStage:
    name = "produce"
    allow_web = False
    workspaceless = False

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def reads(self) -> list[str]:
        return ["concept"]

    def prepare_turn(self, workdir: Path) -> None:
        prepare_turn(workdir)

    def artifact_dirs(self) -> list[str]:
        return ["music", "animation"]

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return finalize_blockers(workdir)

    def status_summary(self, workdir: Path) -> str:
        return status_summary(workdir)


STAGE = ProduceStage()
