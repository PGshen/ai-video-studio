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

WORKSPACELESS_STAGES = frozenset({"brainstorm"})
"""不属于任何项目、没有工作区的阶段（设计 §3.1：头脑风暴会话 `project_id` 为空）。
这些阶段的会话 `project_id is None`，TurnRunner 走「无工作区」模式：没有快照、没有
`upstream/`、没有越界检查，cwd 是每轮重置的 scratch 目录。其余阶段必须有项目。"""


@runtime_checkable
class StageDefinition(Protocol):
    name: str
    allow_web: bool
    """是否给 agent 开放联网工具（设计 §4.2：只有 brainstorm/topic 联网）。"""

    def system_prompt(self) -> str: ...

    def tools(self) -> list[ToolSpec]: ...

    def write_scope(self) -> WriteScope: ...

    def upstream_stages(self) -> list[str]: ...

    def artifact_dirs(self) -> list[str]: ...

    def status_summary(self, workdir: Path) -> str: ...


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
