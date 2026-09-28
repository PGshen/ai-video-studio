"""动画阶段占位定义（设计 §4.3、§5.3）。

M1 只提供占位提示词和 §4.3 的可写范围；`validate_scenes` 等业务工具、
成片渲染在实现动画阶段业务逻辑时补充。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.animation.validate_scenes import VALIDATE_SCENES_TOOL
from studio.workspace import files
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(writable=["animation/scenes/**"], tool_managed=[])
_TOOLS: list[ToolSpec] = [VALIDATE_SCENES_TOOL]
"""`validate_scenes`（T7）不需要 `Engine`，模块加载时就能建好、直接放进
`tools()`。`suggest_upstream_change`（T6）需要 `Engine` 才能构造 `ToolSpec`
（工厂函数 `build_suggest_upstream_change_tool`），`AnimationStage.tools()`
拿不到 `Engine`，暂未接入（决策记录 D22/TD-32）。`render_preview`（T8）同样
不需要 `Engine`，接入方式跟 `validate_scenes` 一样。
"""


class AnimationStage:
    name = "animation"
    allow_web = False

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def upstream_stages(self) -> list[str]:
        return ["narrative"]

    def artifact_dirs(self) -> list[str]:
        return ["animation/scenes"]

    def status_summary(self, workdir: Path) -> str:
        count = sum(1 for path in files.list_tree(workdir) if path.startswith("animation/scenes/"))
        return f"animation/scenes/ 下有 {count} 个文件"


STAGE = AnimationStage()
