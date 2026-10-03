"""TurnRunner 内部共享的数据结构：一个排队中/运行中的 turn（`_Job`）以及一轮
运行中累积、供收尾阶段使用的状态（`_State`）。

拆自 `runner.py`（TD-15）：`runner.py`、`turn_events.py`、`turn_finish.py`、
`recovery.py` 都要引用这两个类型，放在独立模块避免互相 import。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from studio.agent import events
from studio.agent.runtime import CancelToken, UserInput
from studio.agent.stage import StageDefinition
from studio.db.repo.profiles import ModelProfileValue
from studio.db.repo.sessions import SessionValue
from studio.workspace import Manifest


@dataclass
class _Job:
    turn_id: str
    session: SessionValue
    project_id: str | None
    """`None`：无项目会话（头脑风暴），走「无工作区」模式（`StageDefinition.workspaceless`）。"""
    stage: StageDefinition
    profile: ModelProfileValue
    user_input: UserInput
    cancel_token: CancelToken = field(default_factory=CancelToken)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    shutdown: bool = False
    """进程关闭时被停下：`cancelled` 记为 `interrupted`（可以"继续"），快照记 `partial`。"""

    @property
    def busy_key(self) -> str:
        """串行化的键：项目 turn 按项目串行（共用一个工作区）；无项目 turn 各会话独立，
        不阻塞项目 turn，也不被项目 turn 阻塞。"""
        return self.project_id if self.project_id is not None else f"session:{self.session.id}"


@dataclass
class _State:
    """一轮运行中累积的状态，`_finish` 据此收尾。"""

    before: Manifest | None = None
    upstream_ids: dict[str, str | None] = field(default_factory=dict)
    sources: dict[str, Manifest | None] | None = None
    tool_writes: dict[str, str] = field(default_factory=dict)
    pending_tool_paths: list[str] = field(default_factory=list)
    calls: dict[str, events.ToolCall] = field(default_factory=dict)
    steps: int = 0
    input_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_advisory: bool = False
    cost_unpriced: bool = False
    """收到过 `Usage.priced == False`：模型配置缺单价，成本没有统计（turn 的
    `cost_usd` 记为空，并发一次 `cost_unpriced` 提示）。"""
    cost_carryover: bool = False
    """收到过 `Usage.includes_carryover`：`cost_usd` 含上一轮被打断时的残余花费（TD-25）。"""
    budget_exceeded: bool = False
    announced_suggestions: set[str] = field(default_factory=set)
    """已经给会话发过 `suggestion` 事件的回退建议 id（M5 T9），避免同一条发两次。"""
    end: events.TurnEnd | None = None
    status: str | None = None
    """异常路径强制的最终状态（`failed`/`cancelled`），优先于 `end.status`。"""
    error: str | None = None

    def final_status(self) -> tuple[str, str | None]:
        # Budget wins over everything: once exceeded, the runner itself stopped the
        # turn, so a forced task.cancel() or an error raised while stopping is a
        # consequence, not the cause.
        if self.budget_exceeded:
            return "budget_exceeded", self.error
        if self.status is not None:
            return self.status, self.error
        if self.end is not None:
            return self.end.status, self.end.error
        return "failed", "运行时没有产出 TurnEnd 就结束了"
