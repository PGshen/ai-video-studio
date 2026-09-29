"""选题打磨阶段（设计 §4.3、§5.1；计划 M4 T6）。

产物 `topic/brief.md`（结构见 `brief.py`）与调研笔记 `topic/notes/`；工具：联网搜索/抓取
（`stages.common.web_tools`）和 `check_brief`。定稿条件是 `check_brief` 没有错误，由用户确认
（后端 `finalize` 不强制，见计划 D4）。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.common import FETCH_URL_TOOL, WEB_SEARCH_TOOL
from studio.stages.topic.brief import check_workspace
from studio.stages.topic.check_brief import CHECK_BRIEF_TOOL
from studio.workspace import files
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(writable=["topic/**"], tool_managed=[])
_TOOLS: list[ToolSpec] = [WEB_SEARCH_TOOL, FETCH_URL_TOOL, CHECK_BRIEF_TOOL]


class TopicStage:
    name = "topic"
    allow_web = True
    """本阶段允许联网；具体用自建工具还是原生工具由 `STUDIO_WEB_MODE` 决定（ADR 0010）。"""

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def upstream_stages(self) -> list[str]:
        return []

    def artifact_dirs(self) -> list[str]:
        return ["topic"]

    def status_summary(self, workdir: Path) -> str:
        count = sum(1 for path in files.list_tree(workdir) if path.startswith("topic/"))
        result = check_workspace(workdir)
        return (
            f"topic/ 下有 {count} 个文件；brief.md 检查："
            f"{len(result.errors)} 个错误、{len(result.warnings)} 条警告"
        )


STAGE = TopicStage()
