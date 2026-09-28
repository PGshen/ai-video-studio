from __future__ import annotations

import asyncio

import pytest

from studio.agent.bus import BusEvent, SessionBus


async def _next(agen) -> BusEvent:
    return await asyncio.wait_for(agen.__anext__(), timeout=1)


class TestBusEvent:
    def test_persistent_event_carries_seq(self) -> None:
        event = BusEvent(type="text", payload={"text": "hi"}, seq=3)
        assert event.is_transient is False

    def test_transient_event_types_have_no_seq_by_default(self) -> None:
        event = BusEvent(type="text_delta", payload={"text": "h"})
        assert event.seq is None
        assert event.is_transient is True

    @pytest.mark.parametrize("event_type", ["text_delta", "workspace_changed", "turn_status"])
    def test_known_transient_types(self, event_type: str) -> None:
        assert BusEvent(type=event_type, payload={}).is_transient is True

    @pytest.mark.parametrize(
        "event_type",
        ["text", "tool_call", "tool_result", "snapshot", "suggestion", "notice", "error"],
    )
    def test_known_persistent_types(self, event_type: str) -> None:
        assert BusEvent(type=event_type, payload={}).is_transient is False


class TestSessionBusFanout:
    async def test_single_subscriber_receives_published_event(self) -> None:
        bus = SessionBus()
        subscriber = bus.subscribe("session-1")

        bus.publish("session-1", BusEvent(type="text", payload={"text": "hi"}, seq=1))

        event = await _next(subscriber)
        assert event.payload == {"text": "hi"}

    async def test_multiple_subscribers_each_get_their_own_copy(self) -> None:
        bus = SessionBus()
        first = bus.subscribe("session-1")
        second = bus.subscribe("session-1")

        bus.publish("session-1", BusEvent(type="text", payload={"text": "hi"}, seq=1))

        assert (await _next(first)).payload == {"text": "hi"}
        assert (await _next(second)).payload == {"text": "hi"}

    async def test_events_for_other_sessions_are_not_delivered(self) -> None:
        bus = SessionBus()
        subscriber = bus.subscribe("session-1")

        bus.publish("session-2", BusEvent(type="text", payload={"text": "other"}, seq=1))
        bus.publish("session-1", BusEvent(type="text", payload={"text": "mine"}, seq=1))

        event = await _next(subscriber)
        assert event.payload == {"text": "mine"}


class TestSessionBusSlowSubscriber:
    async def test_transient_events_are_dropped_when_queue_is_full(self) -> None:
        bus = SessionBus(queue_size=2)
        subscriber = bus.subscribe("session-1")

        for i in range(5):
            bus.publish("session-1", BusEvent(type="text_delta", payload={"i": i}))

        first = await _next(subscriber)
        second = await _next(subscriber)
        # 队列容量为 2：只保留最后写入队列的两条瞬时事件（前面的已被挤掉）。
        assert first.payload == {"i": 3}
        assert second.payload == {"i": 4}

    async def test_persistent_event_is_never_dropped_even_when_queue_full_of_transient(
        self,
    ) -> None:
        bus = SessionBus(queue_size=2)
        subscriber = bus.subscribe("session-1")

        bus.publish("session-1", BusEvent(type="text_delta", payload={"i": 0}))
        bus.publish("session-1", BusEvent(type="text_delta", payload={"i": 1}))
        # 瞬时事件的队列已满（2 条），此时发布一条持久事件必须仍然送达——
        # 持久事件走独立的无界队列，不受瞬时队列容量影响。
        bus.publish("session-1", BusEvent(type="text", payload={"text": "important"}, seq=1))

        delivered = [await _next(subscriber) for _ in range(3)]
        persistent = [e for e in delivered if not e.is_transient]
        assert len(persistent) == 1
        assert persistent[0].payload == {"text": "important"}

    async def test_persistent_event_overtakes_evicted_transient_events(self) -> None:
        # 瞬时事件即使被挤掉，持久事件也不会因此"排在被挤掉的瞬时事件后面"
        # 卡住——一旦瞬时事件被丢弃，它就不再参与顺序合并。
        bus = SessionBus(queue_size=1)
        subscriber = bus.subscribe("session-1")

        bus.publish("session-1", BusEvent(type="text_delta", payload={"i": 0}))
        bus.publish("session-1", BusEvent(type="text_delta", payload={"i": 1}))  # 挤掉 i=0
        bus.publish("session-1", BusEvent(type="text", payload={"text": "important"}, seq=1))

        first = await _next(subscriber)
        second = await _next(subscriber)
        assert first.payload == {"i": 1}
        assert second.payload == {"text": "important"}

    async def test_persistent_events_are_never_dropped_under_overload(self) -> None:
        # 队列容量只有 2，但发布的持久事件远超容量：持久事件不受容量限制，
        # 必须一条不少地全部送达（控制者裁定：永不丢弃持久事件）。
        bus = SessionBus(queue_size=2)
        subscriber = bus.subscribe("session-1")
        total = 50

        for i in range(total):
            bus.publish("session-1", BusEvent(type="text", payload={"i": i}, seq=i))

        delivered = [await _next(subscriber) for _ in range(total)]
        assert [e.payload["i"] for e in delivered] == list(range(total))

    async def test_persistent_events_keep_relative_order_around_dropped_transient(self) -> None:
        # 持久事件和瞬时事件混合发布时，只要没有事件被丢弃，相对到达顺序应该
        # 保持；这里瞬时事件的队列足够大（未触发丢弃），用来验证合并顺序。
        bus = SessionBus(queue_size=10)
        subscriber = bus.subscribe("session-1")

        bus.publish("session-1", BusEvent(type="text", payload={"label": "p1"}, seq=1))
        bus.publish("session-1", BusEvent(type="text_delta", payload={"label": "t1"}))
        bus.publish("session-1", BusEvent(type="text", payload={"label": "p2"}, seq=2))

        delivered = [await _next(subscriber) for _ in range(3)]
        assert [e.payload["label"] for e in delivered] == ["p1", "t1", "p2"]

    async def test_close_after_partial_iteration_unsubscribes(self) -> None:
        bus = SessionBus()
        subscriber = bus.subscribe("session-1")
        bus.publish("session-1", BusEvent(type="text", payload={}, seq=1))
        await _next(subscriber)
        subscriber.close()

        assert bus.subscriber_count("session-1") == 0
        # 关闭后再发布不应该抛异常（订阅者列表里已经移除了这个队列）。
        bus.publish("session-1", BusEvent(type="text", payload={}, seq=2))

    async def test_close_without_ever_iterating_unsubscribes(self) -> None:
        # T8 审查发现的真实 bug：早期实现里 `subscribe()` 返回一个裸的异步
        # 生成器，取消订阅的逻辑写在它的 `finally` 里；Python 对一个从未
        # `__anext__()` 过的"冷"异步生成器调用 `aclose()` 是空操作，不会跑
        # `finally`，导致这种"订阅后从未真正消费任何一条实时事件就断线"的
        # 场景下订阅永久残留。`Subscription.close()` 是同步、直接摘除，不
        # 依赖有没有迭代过，必须在这种最简单的场景下也能归零。
        bus = SessionBus()
        subscriber = bus.subscribe("session-1")

        subscriber.close()

        assert bus.subscriber_count("session-1") == 0

    async def test_close_is_idempotent_and_does_not_touch_other_subscribers(self) -> None:
        bus = SessionBus()
        first = bus.subscribe("session-1")
        bus.subscribe("session-1")  # 同一会话的第二个订阅者，验证不被误删。

        first.close()
        first.close()  # 第二次调用不应该抛异常。

        assert bus.subscriber_count("session-1") == 1
