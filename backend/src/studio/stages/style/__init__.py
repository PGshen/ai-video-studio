"""风格对话阶段（ADR 0019；计划 style-library T9）。

会话属于一套风格（`sessions.subject_id`），没有项目：TurnRunner 把 cwd 设为这套风格的**草稿目录**
（`data/style-drafts/<id>/`），agent 用原生文件工具直接改草稿；用户点「保存」才成为正式版本。
没有快照、`upstream/`、前言；联网关闭；工具只有 `validate_style`。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.style.tools import VALIDATE_STYLE_TOOL
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
# `references/*` 排在最前：fake 运行时的默认脚本把演示文件写在第一个可写目录里。
_WRITE_SCOPE = WriteScope(writable=["references/*", "exemplars/*", "STYLE.md"], tool_managed=[])
_TOOLS: list[ToolSpec] = [VALIDATE_STYLE_TOOL]


class StyleStage:
    name = "style"
    allow_web = False
    workspaceless = True
    """没有项目；工作目录由会话的 `subject_id`（风格 id）决定。"""

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

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []

    def status_summary(self, workdir: Path) -> str:
        return "风格对话直接修改这套风格的草稿，用户点「保存」后才成为正式版本。"


STAGE = StyleStage()

__all__ = ["STAGE", "VALIDATE_STYLE_TOOL", "StyleStage"]
