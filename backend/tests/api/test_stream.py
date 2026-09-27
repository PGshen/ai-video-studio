"""`GET /api/sessions/{id}/stream`（任务简报 T8；评审关注点 2）。

`httpx.AsyncClient` + `ASGITransport`（本项目 api 测试的标准夹具，见
`conftest.py`）在返回响应前会把整个 ASGI 应用调用跑到完成才把数据交还给
调用方（实测记录见 `docs/references/sse-starlette.md`）：对于一个不会自己
结束的 SSE 流，这意味着经 HTTP 层做"收到几条事件后断开重连"这种用例永远
拿不到任何中间数据，只会一直阻塞到 `asyncio.wait_for` 超时。所以：

- 回放、重放/实时交界处去重、瞬时事件转发这些核心逻辑，直接调用
  `studio.api.sessions._stream_events`（这个端点的核心异步生成器）来测试，
  绕开 HTTP 层的缓冲问题；用 `api_env` 夹具拿现成的、已跑过迁移的 `engine`。
- 断线时总线订阅是否被正确关闭，用真实的 HTTP 请求 + 取消对应的
  `asyncio.Task` 来模拟"客户端断开"（asyncio 任务取消在等待点抛
  `CancelledError`，效果与 ASGI 服务器检测到客户端断开一致），验证走完整
  的路由 + 依赖注入链路后，`SessionBus.subscriber_count` 归零。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import Engine

from studio.agent.bus import BusEvent, SessionBus
from studio.api.sessions import _stream_events
from studio.db.repo.sessions import create_session
from studio.db.repo.turns import append_event

from .conftest import ApiEnv


def _session_id(engine: Engine, stage: str = "topic") -> str:
    return create_session(
        engine, project_id="p1", stage=stage, model_profile_id="m1", runtime="fake"
    ).id


async def _next(agen):
    return await asyncio.wait_for(agen.__anext__(), timeout=1)


def _seq_of(message: dict) -> int | None:
    return json.loads(message["data"])["seq"]


class TestStreamEventsReplay:
    async def test_replays_events_after_given_seq(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        for i in range(3):
            append_event(engine, turn_id="t1", session_id=session_id, type="text", payload={"i": i})
        bus = SessionBus()

        gen = _stream_events(engine, bus, session_id, after_seq=1)
        first = await _next(gen)
        assert first["event"] == "text"
        assert first["id"] == "2"
        assert _seq_of(first) == 2
        second = await _next(gen)
        assert second["id"] == "3"

        await gen.aclose()
        assert bus.subscriber_count(session_id) == 0

    async def test_reconnect_with_after_seq_has_no_loss_and_no_duplicates(
        self, api_env: ApiEnv
    ) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        for i in range(3):
            append_event(engine, turn_id="t1", session_id=session_id, type="text", payload={"i": i})
        bus = SessionBus()

        first_connection = _stream_events(engine, bus, session_id, after_seq=0)
        first_message = await _next(first_connection)
        first_seq = _seq_of(first_message)
        assert first_seq is not None and first_seq == 1
        # 模拟客户端只收到 seq=1 就断线（还没来得及消费 seq=2/3）。
        await first_connection.aclose()
        assert bus.subscriber_count(session_id) == 0

        second_connection = _stream_events(engine, bus, session_id, after_seq=first_seq)
        rest = [await _next(second_connection), await _next(second_connection)]
        await second_connection.aclose()

        all_seqs = [_seq_of(first_message), *[_seq_of(m) for m in rest]]
        assert all_seqs == [1, 2, 3]


class TestStreamEventsLive:
    async def test_transient_event_is_forwarded_without_id(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        bus = SessionBus()
        gen = _stream_events(engine, bus, session_id, after_seq=0)

        # 先驱动一步，让生成器真正跑到"订阅完成、等待总线"的状态。
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0)
        bus.publish(session_id, BusEvent(type="text_delta", payload={"text": "hi"}))

        message = await asyncio.wait_for(task, timeout=1)
        assert message["event"] == "text_delta"
        assert "id" not in message
        assert _seq_of(message) is None

        await gen.aclose()

    async def test_boundary_dedup_skips_already_replayed_persistent_event(
        self, api_env: ApiEnv
    ) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        append_event(engine, turn_id="t1", session_id=session_id, type="text", payload={})
        bus = SessionBus()
        gen = _stream_events(engine, bus, session_id, after_seq=0)

        replayed = await _next(gen)
        assert _seq_of(replayed) == 1

        # 总线又推来一条重放阶段已经发过的持久事件（交界处重复），以及一条
        # 真正新的持久事件；前者必须被跳过。
        bus.publish(session_id, BusEvent(type="text", payload={"dup": True}, seq=1))
        bus.publish(session_id, BusEvent(type="text", payload={"new": True}, seq=2))

        live = await _next(gen)
        assert _seq_of(live) == 2
        assert json.loads(live["data"])["new"] is True

        await gen.aclose()

    async def test_aclose_unsubscribes_from_bus(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        bus = SessionBus()
        gen = _stream_events(engine, bus, session_id, after_seq=0)

        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0)
        assert bus.subscriber_count(session_id) == 1

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert bus.subscriber_count(session_id) == 0


class TestStreamEndpointWiring:
    async def test_unknown_session_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/sessions/does-not-exist/stream")
        assert response.status_code == 404

    async def test_client_disconnect_closes_bus_subscription(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        bus: SessionBus = api_env.app.state.bus

        task = asyncio.ensure_future(api_env.client.get(f"/api/sessions/{session_id}/stream"))
        # 给应用足够时间跑到"已订阅、等待总线事件"的挂起点。
        for _ in range(50):
            if bus.subscriber_count(session_id) == 1:
                break
            await asyncio.sleep(0.01)
        assert bus.subscriber_count(session_id) == 1

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)

        assert bus.subscriber_count(session_id) == 0
