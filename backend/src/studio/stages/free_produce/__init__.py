"""`free_produce` 阶段：自由短片与自由 MV 的单阶段（free-mode 设计 §4）。

没有 `concept`：用户在对话里直接提需求；配乐与画面的做法、产物位置与 `produce` 相同，形态同样按
`music/source.*` 是否存在分流。整个工作区可写，联网，没有上游。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.common import FETCH_URL_TOOL, WEB_SEARCH_TOOL
from studio.stages.common.free_scope import free_write_scope
from studio.stages.common.music_source import find_source
from studio.stages.common.produce_flow import finalize_blockers, prepare_turn, status_summary
from studio.stages.common.prompts import compose_prompt, fragment
from studio.stages.common.scenes.render_preview_html import RENDER_PREVIEW_HTML_TOOL
from studio.stages.common.scenes.validate_scenes_html import VALIDATE_SCENES_HTML_TOOL
from studio.stages.common.score.analyze import ANALYZE_MUSIC_TOOL
from studio.stages.common.score.tool import RENDER_MUSIC_TOOL
from studio.workspace.scope import WriteScope

_HERE = Path(__file__).parent
_PROMPT_PARTS = [
    _HERE / "opening.md",
    fragment("free-mode"),
    _HERE / "inputs.md",
    fragment("silent-compose"),
    fragment("silent-song"),
    _HERE / "lyrics.md",
    fragment("silent-scenes"),
]
_WRITE_SCOPE = free_write_scope()
_TOOLS: list[ToolSpec] = [
    WEB_SEARCH_TOOL,
    FETCH_URL_TOOL,
    RENDER_MUSIC_TOOL,
    ANALYZE_MUSIC_TOOL,
    VALIDATE_SCENES_HTML_TOOL,
    RENDER_PREVIEW_HTML_TOOL,
]
_NO_MUSIC = (
    "还没有配乐：自由短片写 music/compose.py 并调用 render_music；"
    "自由 MV 需要用户先在「配乐」标签页上传歌曲"
)


class FreeProduceStage:
    name = "free_produce"
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
        prepare_turn(workdir)

    def artifact_dirs(self) -> list[str]:
        return ["music", "animation"]

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return finalize_blockers(workdir)

    def status_summary(self, workdir: Path) -> str:
        music = workdir / "music"
        if find_source(music) is None and not (music / "render.json").is_file():
            # Without a song or a render the workspace cannot tell a reel from an MV yet.
            return f"{_NO_MUSIC}；{status_summary(workdir).split('；', 1)[-1]}"
        return status_summary(workdir)


STAGE = FreeProduceStage()
