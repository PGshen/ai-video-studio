"""选题打磨阶段占位定义（设计 §4.3、§5.1）。

M1 只提供占位提示词和 §4.3 的可写范围；产物 schema、`check_brief` 等业务
工具、定稿条件在 M4 实现。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.workspace import files
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(writable=["topic/**"], tool_managed=[])


class TopicStage:
    name = "topic"
    allow_web = True

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return []

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def upstream_stages(self) -> list[str]:
        return []

    def artifact_dirs(self) -> list[str]:
        return ["topic"]

    def status_summary(self, workdir: Path) -> str:
        count = sum(1 for path in files.list_tree(workdir) if path.startswith("topic/"))
        return f"topic/ 下有 {count} 个文件"


STAGE = TopicStage()
