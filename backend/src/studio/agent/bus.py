"""会话事件总线（设计 §4.4 步骤 5、7；评审关注点 2）。

`BusEvent` 是推给 SSE 的信封：持久事件（对应 `turn_events` 表：
`text`/`tool_call`/`tool_result`/`snapshot`/`suggestion`/`notice`/`error`，
由 TurnRunner 落库后再发布）带会话内单调递增的 `seq`，用于断线重连的
`after_seq` 续传；瞬时事件（`text_delta` token 级增量、`workspace_changed`
文件类工具调用后的提示、`turn_status` turn 状态变化）不落库，`seq=None`，
重连后不回放（计划决策记录 2026-09-26）。

订阅者的队列有界：正常情况下队列写满说明订阅者（SSE 连接）处理跟不上，
这时必须优先保证持久事件不丢——需要时丢弃队列里最旧的瞬时事件腾出空间；
如果队列里恰好全是持久事件（瞬时事件本就不落库、正常场景很少见），退化
为丢弃最旧的一条持久事件，而不是让 `publish` 阻塞或抛异常（决策记入计划
「决策记录」）。
"""

from __future__ import annotations

import asyncio
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


class SessionBus:
    """按 `session_id` 分组的发布/订阅总线，进程内内存实现（设计 §2.1）。"""

    def __init__(self, *, queue_size: int = 100) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, list[asyncio.Queue[BusEvent]]] = {}

    def subscriber_count(self, session_id: str) -> int:
        return len(self._subscribers.get(session_id, []))

    def publish(self, session_id: str, event: BusEvent) -> None:
        for queue in self._subscribers.get(session_id, []):
            self._deliver(queue, event)

    def _deliver(self, queue: asyncio.Queue[BusEvent], event: BusEvent) -> None:
        try:
            queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass

        evicted_transient = self._evict_oldest_transient(queue)
        if not evicted_transient:
            if event.is_transient:
                # 队列里全是持久事件，新事件本身是瞬时的：丢弃新事件，
                # 一个持久事件都不动。
                return
            # 新事件是持久的，但队列里也全是持久事件：丢弃最旧的一条腾位置，
            # 保证这条新的持久事件仍然送达（决策：见计划「决策记录」）。
            self._evict_oldest(queue)

        queue.put_nowait(event)

    def _evict_oldest_transient(self, queue: asyncio.Queue[BusEvent]) -> bool:
        """丢弃队列里最旧的一条瞬时事件；找到并丢弃返回 `True`，队列里没有
        瞬时事件（全是持久事件）时原样保留并返回 `False`。
        """
        buffered = [queue.get_nowait() for _ in range(queue.qsize())]
        found = False
        for index, buffered_event in enumerate(buffered):
            if buffered_event.is_transient:
                del buffered[index]
                found = True
                break
        for buffered_event in buffered:
            queue.put_nowait(buffered_event)
        return found

    def _evict_oldest(self, queue: asyncio.Queue[BusEvent]) -> None:
        """无条件丢弃队首（最旧）的一条事件。"""
        queue.get_nowait()

    def subscribe(self, session_id: str) -> AsyncGenerator[BusEvent, None]:
        """注册一个新订阅者并返回事件流。

        注意：注册（把队列加进 `self._subscribers`）在这个方法里**同步**
        发生，不是异步生成器函数——如果把注册逻辑写在 `async def` 生成器
        函数体内，Python 不会执行函数体直到第一次 `__anext__()`，那样
        `publish` 在订阅者第一次迭代之前发布的事件就会丢失（因为队列还没
        注册进去）。这里拆成同步的注册 + 单独的异步生成器负责取事件。
        返回类型用 `AsyncGenerator` 而不是更宽泛的 `AsyncIterator`，让调用方
        （包括测试）能用 `aclose()` 主动结束订阅、触发下面的取消订阅逻辑。
        """
        queue: asyncio.Queue[BusEvent] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.setdefault(session_id, []).append(queue)
        return self._pump(session_id, queue)

    async def _pump(
        self, session_id: str, queue: asyncio.Queue[BusEvent]
    ) -> AsyncGenerator[BusEvent, None]:
        try:
            while True:
                yield await queue.get()
        finally:
            subscribers = self._subscribers.get(session_id)
            if subscribers is not None and queue in subscribers:
                subscribers.remove(queue)
