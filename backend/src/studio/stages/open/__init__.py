"""`open` 阶段：完全自由模式的单阶段（open-mode 设计 §4）。

没有提示词（运行时默认：Claude 为 Claude Code 自带提示词）、没有格式契约、没有检查：工作区初始只有
`style/` 与 `project.md`，agent 用什么技术、写哪些文件都自己决定。整个工作区可写，联网，命令也可以
联网（读写隔离不变），自建工具只有 `tts`。定稿就是"标记完成"，没有前置条件。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.common import FETCH_URL_TOOL, WEB_SEARCH_TOOL
from studio.stages.common.narration.tts import TTS_TOOL
from studio.stages.common.open_scope import OPEN_WRITE_SCOPE
from studio.workspace.scope import WriteScope

# Self-built web tools only survive in the `tools` web mode; the runner drops them for native web.
_TOOLS: list[ToolSpec] = [WEB_SEARCH_TOOL, FETCH_URL_TOOL, TTS_TOOL]


class OpenStage:
    name = "open"
    allow_web = True
    workspaceless = False
    exec_network = True

    def system_prompt(self) -> str | None:
        return None

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return OPEN_WRITE_SCOPE

    def reads(self) -> list[str]:
        return []

    def prepare_turn(self, workdir: Path) -> None:
        return None

    def artifact_dirs(self) -> list[str]:
        return []

    def finalize_blockers(self, workdir: Path) -> list[str]:
        return []

    def status_summary(self, workdir: Path) -> str:
        return ""


STAGE = OpenStage()
