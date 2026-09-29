"""阶段定义协议（设计 §4.1；ARCHITECTURE §2 规则 2）。

`agent` 不 import `stages`：TurnRunner 只认识这个结构化协议（提示词、工具
列表、可写范围、上下文前言需要的信息），具体阶段（`stages.topic` 等）在
`main` 中实例化后调用 `StageRegistry.register` 接入，运行时层和业务逻辑
因此解耦。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from studio.agent.tools import ToolSpec
from studio.workspace.scope import WriteScope


@runtime_checkable
class StageDefinition(Protocol):
    name: str
    allow_web: bool
    """本阶段是否允许联网（设计 §4.2：只有 brainstorm/topic 联网）；具体用自建工具还是运行时
    原生联网由 `STUDIO_WEB_MODE` 决定（ADR 0010）。"""
    workspaceless: bool
    """没有项目、没有工作区的阶段（头脑风暴，设计 §3.1）：会话 `project_id` 为空，TurnRunner 走
    「无工作区」模式——没有快照、`upstream/`、越界检查，cwd 是每轮重置的 scratch 目录。其余阶段
    必须有项目。"""

    def system_prompt(self) -> str: ...

    def tools(self) -> list[ToolSpec]: ...

    def write_scope(self) -> WriteScope: ...

    def upstream_stages(self) -> list[str]: ...

    def artifact_dirs(self) -> list[str]: ...

    def status_summary(self, workdir: Path) -> str: ...

    def finalize_blockers(self, workdir: Path) -> list[str]:
        """定稿前必须先解决的问题（中文说明，每条一行）；空列表表示可以定稿。
        由 api 在调用 `stage_flow.finalize` 之前检查，有问题时拒绝定稿（409）。"""
        ...


class StageRegistry:
    """`name -> StageDefinition` 的注册表；由 `main` 装配（M1 不含 brainstorm）。"""

    def __init__(self) -> None:
        self._stages: dict[str, StageDefinition] = {}

    def register(self, stage: StageDefinition) -> None:
        self._stages[stage.name] = stage

    def get(self, name: str) -> StageDefinition:
        try:
            return self._stages[name]
        except KeyError as exc:
            raise KeyError(f"未注册的阶段：{name}") from exc
