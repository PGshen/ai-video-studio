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
        # 队列已满（2 条瞬时事件），此时发布一条持久事件必须仍然送达。
        bus.publish("session-1", BusEvent(type="text", payload={"text": "important"}, seq=1))

        delivered = [await _next(subscriber) for _ in range(2)]
        persistent = [e for e in delivered if not e.is_transient]
        assert len(persistent) == 1
        assert persistent[0].payload == {"text": "important"}

    async def test_persistent_events_are_never_dropped_for_each_other(self) -> None:
        bus = SessionBus(queue_size=2)
        subscriber = bus.subscribe("session-1")

        for i in range(4):
            bus.publish("session-1", BusEvent(type="text", payload={"i": i}, seq=i))

        delivered = [await _next(subscriber) for _ in range(2)]
        # 队列容量为 2 且全是持久事件：新事件到达时必须挤掉最旧的一条持久事件，
        # 而不能丢弃新事件或无限增长队列。
        assert [e.payload["i"] for e in delivered] == [2, 3]

    async def test_unsubscribed_queue_stops_receiving_after_generator_closed(self) -> None:
        bus = SessionBus()
        subscriber = bus.subscribe("session-1")
        # 先消费一条，让生成器真正启动（挂起在下一次 `await queue.get()`），
        # 再 `aclose()` 才会触发 `finally` 里的取消订阅逻辑。
        bus.publish("session-1", BusEvent(type="text", payload={}, seq=1))
        await _next(subscriber)
        await subscriber.aclose()

        assert bus.subscriber_count("session-1") == 0
        # 关闭后再发布不应该抛异常（订阅者列表里已经移除了这个队列）。
        bus.publish("session-1", BusEvent(type="text", payload={}, seq=2))
