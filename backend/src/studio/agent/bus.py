"""会话事件总线（设计 §4.4 步骤 5、7；评审关注点 2）。

`BusEvent` 是推给 SSE 的信封：持久事件（对应 `turn_events` 表：
`text`/`tool_call`/`tool_result`/`snapshot`/`suggestion`/`notice`/`error`，
由 TurnRunner 落库后再发布）带会话内单调递增的 `seq`，用于断线重连的
`after_seq` 续传；瞬时事件（`text_delta` token 级增量、`workspace_changed`
文件类工具调用后的提示、`turn_status` turn 状态变化）不落库，`seq=None`，
重连后不回放（计划决策记录 2026-09-26）。

订阅者慢（SSE 连接处理跟不上）时的兜底策略（审查后修复，控制者裁定）：
**持久事件永不因为容量限制被丢弃**——每个订阅者内部拆成两条队列：

- 瞬时事件走一条有界队列（容量 `queue_size`），写满时丢弃队列里最旧的一条
  腾出位置给新事件（滑动窗口：保留最新的一批瞬时事件）；
- 持久事件走一条无界队列，永远接受新事件，`publish` 不会因为它阻塞或
  抛异常。

两条队列合并的顺序：每个事件在 `publish` 时打上一个总线全局的单调递增
内部序号（和 `BusEvent.seq`——会话内的持久事件序号——是两个不同的概念），
订阅者的抽取协程（`_pump`）总是从两条队列的队首中选内部序号更小的一个先
产出，这样"瞬时事件和持久事件之间的相对到达顺序"在没有事件被丢弃的情况下
能尽量保持；瞬时事件本身因为丢弃可能出现顺序上的空洞，这是设计允许的
（瞬时事件不保证送达）。
"""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

TRANSIENT_EVENT_TYPES = frozenset({"text_delta", "workspace_changed", "turn_status"})


@dataclass(frozen=True, slots=True)
class BusEvent:
    """推给 SSE 的事件信封。"""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int | None = None

    @property
    def is_transient(self) -> bool:
        return self.type in TRANSIENT_EVENT_TYPES


class _Subscriber:
    """单个订阅者的状态：一条有界瞬时队列 + 一条无界持久队列，靠内部序号
    合并成一条有序的事件流。
    """

    def __init__(self, queue_size: int) -> None:
        self._queue_size = queue_size
        self._transient: deque[tuple[int, BusEvent]] = deque()
        self._persistent: deque[tuple[int, BusEvent]] = deque()
        self._has_data = asyncio.Event()

    def push(self, order: int, event: BusEvent) -> None:
        if event.is_transient:
            self._transient.append((order, event))
            while len(self._transient) > self._queue_size:
                self._transient.popleft()
        else:
            # 持久事件永远接受，队列本身无界，不做任何容量检查。
            self._persistent.append((order, event))
        self._has_data.set()

    async def pump(self) -> AsyncGenerator[BusEvent, None]:
        while True:
            while not self._transient and not self._persistent:
                await self._has_data.wait()
                self._has_data.clear()

            if self._transient and self._persistent:
                if self._transient[0][0] < self._persistent[0][0]:
                    _, event = self._transient.popleft()
                else:
                    _, event = self._persistent.popleft()
            elif self._transient:
                _, event = self._transient.popleft()
            else:
                _, event = self._persistent.popleft()

            yield event


class SessionBus:
    """按 `session_id` 分组的发布/订阅总线，进程内内存实现（设计 §2.1）。"""

    def __init__(self, *, queue_size: int = 100) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, list[_Subscriber]] = {}
        self._order_counter = itertools.count()

    def subscriber_count(self, session_id: str) -> int:
        return len(self._subscribers.get(session_id, []))

    def publish(self, session_id: str, event: BusEvent) -> None:
        order = next(self._order_counter)
        for subscriber in self._subscribers.get(session_id, []):
            subscriber.push(order, event)

    def subscribe(self, session_id: str) -> AsyncGenerator[BusEvent, None]:
        """注册一个新订阅者并返回事件流。

        注意：注册（把订阅者加进 `self._subscribers`）在这个方法里**同步**
        发生，不是异步生成器函数——如果把注册逻辑写在 `async def` 生成器
        函数体内，Python 不会执行函数体直到第一次 `__anext__()`，那样
        `publish` 在订阅者第一次迭代之前发布的事件就会丢失（因为订阅者还没
        注册进去）。这里拆成同步的注册 + 单独的异步生成器负责取事件。
        返回类型用 `AsyncGenerator` 而不是更宽泛的 `AsyncIterator`，让调用方
        （包括测试）能用 `aclose()` 主动结束订阅、触发下面的取消订阅逻辑。
        """
        subscriber = _Subscriber(self._queue_size)
        self._subscribers.setdefault(session_id, []).append(subscriber)
        return self._pump(session_id, subscriber)

    async def _pump(
        self, session_id: str, subscriber: _Subscriber
    ) -> AsyncGenerator[BusEvent, None]:
        try:
            async for event in subscriber.pump():
                yield event
        finally:
            subscribers = self._subscribers.get(session_id)
            if subscribers is not None and subscriber in subscribers:
                subscribers.remove(subscriber)
