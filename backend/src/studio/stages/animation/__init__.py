"""动画阶段占位定义（设计 §4.3、§5.3）。

M1 只提供占位提示词和 §4.3 的可写范围；`validate_scenes` 等业务工具、
成片渲染在实现动画阶段业务逻辑时补充。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.workspace import files
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(writable=["animation/scenes/**"], tool_managed=[])


class AnimationStage:
    name = "animation"
    allow_web = False

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return []

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
