"""头脑风暴阶段（设计 §5.0；计划 M4 T3/T4）。

没有项目、没有工作区（决策 D2）：可写范围为空，业务工具（T4 的 `list_ideas`/
`create_idea`/`update_idea`）只读写 `ideas` 表。T3 先提供阶段骨架（占位提示词、空工具集），
让无项目会话的运行时路径有一个真实的阶段定义可以测试；T4 补工具和完整提示词。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.brainstorm.tools import CREATE_IDEA_TOOL, LIST_IDEAS_TOOL, UPDATE_IDEA_TOOL
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(writable=[], tool_managed=[])
_TOOLS: list[ToolSpec] = [LIST_IDEAS_TOOL, CREATE_IDEA_TOOL, UPDATE_IDEA_TOOL]


class BrainstormStage:
    name = "brainstorm"
    allow_web = False  # T5 加联网模式开关时和 topic 一起改为 True

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def upstream_stages(self) -> list[str]:
        return []

    def artifact_dirs(self) -> list[str]:
        return []

    def status_summary(self, workdir: Path) -> str:
        return "头脑风暴没有工作区文件，想法卡片保存在选题池里。"


STAGE = BrainstormStage()
