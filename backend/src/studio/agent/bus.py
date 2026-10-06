"""会话事件总线（设计 §4.4 步骤 5、7；评审关注点 2）。

`BusEvent` 是推给 SSE 的信封：持久事件（对应 `turn_events` 表：
`text`/`tool_call`/`tool_result`/`snapshot`/`suggestion`/`notice`/`error`，
由 TurnRunner 落库后再发布；`suggestion` 是设计 §3.1 列出的持久事件类型，
M1 还没有任何代码产出它——回退建议在 M4 才实现，见 `docs/glossary.md`）带
会话内单调递增的 `seq`，用于断线重连的 `after_seq` 续传；瞬时事件
（`text_delta` token 级增量、`workspace_changed` 文件类工具调用后的提示、
`turn_status` turn 状态变化）不落库，`seq=None`，重连后不回放（计划决策记录
2026-09-26）。T8 的 SSE 端点实际转发的 9 种线上事件名见
`studio.api.sessions.WIRE_EVENT_TYPES`。

订阅者慢（SSE 连接处理跟不上）时的兜底策略（审查后修复，控制者裁定）：
**持久事件永不因为容量限制被丢弃**——每个订阅者内部拆成两条队列：

- 瞬时事件走一条有界队列（容量 `queue_size`），写满时丢弃队列里最旧的一条
  腾出位置给新事件（滑动窗口：保留最新的一批瞬时事件）；
- 持久事件走一条无界队列，永远接受新事件，`publish` 不会因为它阻塞或
  抛异常。

两条队列合并的顺序：每个事件在 `publish` 时打上一个总线全局的单调递增
内部序号（和 `BusEvent.seq`——会话内的持久事件序号——是两个不同的概念），
订阅者的抽取协程（`_Subscriber.pump`）总是从两条队列的队首中选内部序号更小
的一个先产出，这样"瞬时事件和持久事件之间的相对到达顺序"在没有事件被丢弃
的情况下能尽量保持；瞬时事件本身因为丢弃可能出现顺序上的空洞，这是设计
允许的（瞬时事件不保证送达）。

`subscribe()` 返回的是 `Subscription`（不是裸的异步生成器）：`close()` 是
**同步、幂等**的方法，直接把订阅者从 `_subscribers` 列表里摘掉，不依赖
"这个订阅有没有被迭代过"（T8 审查发现的真实 bug：早期实现让 `subscribe()`
直接返回一个包了 `try/finally` 的异步生成器，`finally` 里做取消订阅——但
Python 对一个从未 `__anext__()` 过的"冷"异步生成器调用 `aclose()` 是空
操作，不会跑它的 `finally`；如果一次 SSE 连接的全部数据都靠回放已落库
事件满足、从未真正走到订阅总线取实时事件那一步就断开，订阅就会永久残留）。
`Subscription` 把"清理"和"生成器有没有被驱动过"彻底解耦，调用方（`_stream_events`
的 `finally`）无论有没有真正消费过任何一条实时事件，调用一次 `close()` 都
能正确摘除订阅。
"""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Any

TRANSIENT_EVENT_TYPES = frozenset(
    {"text_delta", "thinking_delta", "workspace_changed", "turn_status", "session_title"}
)


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


class Subscription:
    """`SessionBus.subscribe()` 返回的句柄：异步迭代事件 + 同步取消订阅。

    `close()` 是同步、幂等的方法：不管这个订阅有没有被迭代过、迭代了几次，
    调用一次就能把对应的 `_Subscriber` 从总线的 `_subscribers` 列表里摘掉。
    不通过关闭某个异步生成器来触发清理，因此不受"异步生成器从未
    `__anext__()` 过时 `aclose()` 是空操作"这条 Python 行为的影响（T8 审查
    发现的真实 bug，见模块文档）。

    两点容易搞混、复审时特意确认过的语义：

    - **只有显式调用 `close()` 才会取消订阅**——取消一个正在等待
      `__anext__()` 的协程/任务（比如 `task.cancel()`）本身不会让这个
      `Subscription` 从 `_subscribers` 里消失，`_closed` 也不会被置位。
      调用方（例如 `_stream_events`）依赖的是自己 `finally` 里的
      `subscription.close()`，不是"等待被取消"这件事本身；如果只
      `task.cancel()` 而不调用 `close()`，订阅仍然会残留在总线里。
    - `close()` **不会唤醒**另一个协程里正挂起在 `await subscription.__anext__()`
      的等待——它只是同步地把订阅者从列表里摘掉，之后总线的 `publish()`
      不会再往这个订阅者的队列里塞新事件，但已经发起的那次 `__anext__()`
      调用不会因为别处调用了 `close()` 就提前返回或抛异常，会继续挂起，
      直到有新事件、或者调用方自己取消这次等待。正确用法是让"停止等待"
      和 `close()` 发生在同一个协程里、按顺序执行，就像 `_stream_events`
      的 `finally` 那样（先退出 `async for`，再 `close()`），不要指望从另一
      个任务调用 `close()` 能顺带打断这里的等待。
    """

    def __init__(self, bus: SessionBus, session_id: str, subscriber: _Subscriber) -> None:
        self._bus = bus
        self._session_id = session_id
        self._subscriber = subscriber
        self._pump = subscriber.pump()
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        subscribers = self._bus._subscribers.get(self._session_id)
        if subscribers is not None and self._subscriber in subscribers:
            subscribers.remove(self._subscriber)

    def __aiter__(self) -> AsyncIterator[BusEvent]:
        return self

    async def __anext__(self) -> BusEvent:
        if self._closed:
            raise StopAsyncIteration
        return await self._pump.__anext__()


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

    def subscribe(self, session_id: str) -> Subscription:
        """注册一个新订阅者并返回 `Subscription`。

        注册（把订阅者加进 `self._subscribers`）在这个方法里**同步**发生——
        如果注册逻辑写在异步生成器函数体内，Python 不会执行函数体直到第
        一次 `__anext__()`，那样 `publish` 在订阅者第一次迭代之前发布的
        事件就会丢失（因为订阅者还没注册进去）。
        """
        subscriber = _Subscriber(self._queue_size)
        self._subscribers.setdefault(session_id, []).append(subscriber)
        return Subscription(self, session_id, subscriber)
