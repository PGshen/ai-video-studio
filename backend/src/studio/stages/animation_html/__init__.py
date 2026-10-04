"""`animation_html` 阶段：用 Canvas 2D 场景做画面（子项目 2 设计 §6）。

agent 在 `animation/scenes/<镜头 id>.js` 里写 `{ draw(ctx, lt, env), pad? }`，用
`validate_scenes_html` / `render_preview_html` 自检。系统不提供绘图库，只提供页面运行时
（`engines.render.html`）和 `upstream/timeline.json`。
"""

from __future__ import annotations

import json
from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.animation_html.prepare import TIMELINE_PATH, prepare_turn
from studio.stages.animation_html.render_preview_html import RENDER_PREVIEW_HTML_TOOL
from studio.stages.animation_html.validate_scenes_html import VALIDATE_SCENES_HTML_TOOL
from studio.stages.common import SUGGEST_UPSTREAM_CHANGE_TOOL
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(
    writable=[
        "animation/scenes/*.js",
        "animation/lib/*.js",
        "animation/global.js",
        "animation/assets/*",
    ],
    tool_managed=[],
)
_TOOLS: list[ToolSpec] = [
    VALIDATE_SCENES_HTML_TOOL,
    RENDER_PREVIEW_HTML_TOOL,
    SUGGEST_UPSTREAM_CHANGE_TOOL,
]


class AnimationHtmlStage:
    name = "animation_html"
    allow_web = False
    workspaceless = False

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def reads(self) -> list[str]:
        return ["narrative", "beatsheet", "music"]

    def prepare_turn(self, workdir: Path) -> None:
        prepare_turn(workdir)

    def artifact_dirs(self) -> list[str]:
        # `stage_flow` 按“目录加斜杠”做前缀匹配，单文件（animation/global.js）写不进去，
        # 整个 animation/ 目录即可：一条流水线里只会有一个动画阶段。
        return ["animation"]

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []

    def status_summary(self, workdir: Path) -> str:
        scenes = sorted((workdir / "animation" / "scenes").glob("*.js"))
        total: int | str = "未知"
        timeline = workdir / TIMELINE_PATH
        if timeline.is_file():
            total = len(json.loads(timeline.read_text(encoding="utf-8")).get("sections", []))
        return f"scenes/ 下已写 {len(scenes)} 个镜头 / 时间轴共 {total} 个镜头"


STAGE = AnimationHtmlStage()
