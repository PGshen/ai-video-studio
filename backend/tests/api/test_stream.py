"""`GET /api/sessions/{id}/stream`（任务简报 T8；评审关注点 2）。

`httpx.AsyncClient` + `ASGITransport`（本项目 api 测试的标准夹具，见
`conftest.py`）在返回响应前会把整个 ASGI 应用调用跑到完成才把数据交还给
调用方（实测记录见 `docs/references/sse-starlette.md`），不支持真正的增量
流式读取——对于一个不会自己结束的 SSE 流，经它做"收到几条事件后断开重连"
这种用例永远拿不到任何中间数据，只会一直阻塞到 `asyncio.wait_for` 超时。
所以分两层测试：

- 回放、重放/实时交界处去重、瞬时事件转发、未知事件类型过滤这些核心逻辑，
  直接调用 `studio.api.sessions._stream_events`（这个端点的核心异步生成器）
  来测试，绕开 HTTP 层。
- HTTP 层（响应头、SSE 帧的 `id`/`event`/`data` 格式、`Last-Event-ID`、
  真实断线时的清理、断线重连端到端不丢不重）用 `_drive` 直接驱动
  `app(scope, receive, send)`——自己实现 `receive`/`send` 两个 ASGI 回调，
  绕开 `httpx.ASGITransport` 的全量缓冲，能拿到真正逐块到达的响应体；
  `receive()` 在 `disconnect` 事件被置位前一直挂起，模拟"客户端还连着"，
  置位后返回 `{"type": "http.disconnect"}`，效果等价于真实的客户端断开。

审查后发现的另一个环境问题：`sse_starlette.sse.AppStatus.should_exit_event`
是进程级单例，第一次被用到时惰性创建并绑定到当时的事件循环；本项目
`pytest-asyncio` 默认给每个测试函数一个新的事件循环（`asyncio_mode=auto`，
`asyncio_default_test_loop_scope` 未设置即为 function 级），第二个真正跑到
`EventSourceResponse.__call__` 的测试就会在一个不同的循环上 `await` 这个
绑定了旧循环的 `anyio.Event`，报 "is bound to a different event loop"。下面
的 `_reset_sse_starlette_app_status` 自动夹具在每个测试前后把它清空。
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import sse_starlette.sse as sse_starlette_sse
from sqlalchemy import Engine

from event_asserts import assert_in_order, type_counts
from studio.agent import events
from studio.agent.bus import BusEvent, SessionBus
from studio.api.sessions import WIRE_EVENT_TYPES, _stream_events
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.turns import append_event

from .conftest import ApiEnv


@pytest.fixture(autouse=True)
def _reset_sse_starlette_app_status():
    sse_starlette_sse.AppStatus.should_exit_event = None
    sse_starlette_sse.AppStatus.should_exit = False
    yield
    sse_starlette_sse.AppStatus.should_exit_event = None
    sse_starlette_sse.AppStatus.should_exit = False


def _session_id(engine: Engine, stage: str = "topic") -> str:
    return create_session(
        engine, project_id="p1", stage=stage, model_profile_id="m1", runtime="fake"
    ).id


async def _next(agen: Any) -> dict[str, Any]:
    return await asyncio.wait_for(agen.__anext__(), timeout=1)


def _seq_of(message: dict[str, Any]) -> int | None:
    return json.loads(message["data"])["seq"]


async def _wait_until(predicate: Any, timeout: float = 1.0, interval: float = 0.005) -> None:
    async def _loop() -> None:
        while not predicate():
            await asyncio.sleep(interval)

    await asyncio.wait_for(_loop(), timeout)


# ---------------------------------------------------------------------------
# 白盒测试：直接调用 `_stream_events`
# ---------------------------------------------------------------------------


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

    async def test_aclose_without_ever_reaching_live_events_unsubscribes(
        self, api_env: ApiEnv
    ) -> None:
        """T8 审查发现的真实 bug 的回归测试：一次连接的全部数据都靠回放
        满足、从未走到 `async for` 转发实时事件那一步就断线，也必须正确
        取消订阅（`agent.bus.Subscription.close()` 同步、幂等，不依赖生成器
        有没有被迭代过）。
        """
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        append_event(engine, turn_id="t1", session_id=session_id, type="text", payload={})
        bus = SessionBus()

        gen = _stream_events(engine, bus, session_id, after_seq=0)
        message = await _next(gen)
        assert _seq_of(message) == 1

        await gen.aclose()

        assert bus.subscriber_count(session_id) == 0


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

    async def test_cancelling_pending_anext_unsubscribes_from_bus(self, api_env: ApiEnv) -> None:
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


class TestWireEventTypesEnforcement:
    async def test_unknown_persisted_type_is_skipped_on_replay(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        append_event(engine, turn_id="t1", session_id=session_id, type="mystery", payload={})
        append_event(engine, turn_id="t1", session_id=session_id, type="text", payload={})
        bus = SessionBus()

        gen = _stream_events(engine, bus, session_id, after_seq=0)
        first = await _next(gen)

        assert first["event"] == "text"
        assert _seq_of(first) == 2
        await gen.aclose()

    async def test_unknown_live_type_is_skipped(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        bus = SessionBus()
        gen = _stream_events(engine, bus, session_id, after_seq=0)

        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0)
        bus.publish(session_id, BusEvent(type="mystery", payload={}))
        bus.publish(session_id, BusEvent(type="text_delta", payload={"text": "hi"}))

        message = await asyncio.wait_for(task, timeout=1)
        assert message["event"] == "text_delta"
        await gen.aclose()

    def test_wire_event_types_has_exactly_the_documented_names(self) -> None:
        """T8 简报列出 9 种；M5 T9 增加 `suggestion`（回退建议），共 10 种。"""
        assert WIRE_EVENT_TYPES == {
            "text_delta",
            "text",
            "tool_call",
            "tool_result",
            "snapshot",
            "suggestion",
            "notice",
            "error",
            "workspace_changed",
            "turn_status",
        }


# ---------------------------------------------------------------------------
# HTTP 层：直接驱动 ASGI app（不经过 httpx.ASGITransport）
# ---------------------------------------------------------------------------


def _scope(path: str, *, query: str = "", headers: dict[str, str] | None = None) -> dict[str, Any]:
    all_headers = {"host": "127.0.0.1:8000", **(headers or {})}
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in all_headers.items()]
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": raw_headers,
        "server": ("test", 80),
        "client": ("test-client", 12345),
    }


@dataclass
class DrivenResponse:
    """直接驱动 ASGI app 得到的响应句柄：逐块收集 body，支持模拟断线。"""

    task: asyncio.Task[Any]
    chunks: list[bytes] = field(default_factory=list)
    start_headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    status: dict[str, int] = field(default_factory=dict)
    disconnect: asyncio.Event = field(default_factory=asyncio.Event)

    def header(self, name: str) -> str | None:
        needle = name.lower().encode()
        for key, value in self.start_headers:
            if key.lower() == needle:
                return value.decode()
        return None

    async def wait_for_status(self, timeout: float = 1.0) -> int:
        await _wait_until(lambda: "status" in self.status, timeout)
        return self.status["status"]

    async def wait_for_frames(self, n: int, timeout: float = 1.0) -> None:
        await _wait_until(lambda: len(self.chunks) >= n, timeout)

    def disconnect_now(self) -> None:
        self.disconnect.set()

    async def finish(self, timeout: float = 1.0) -> None:
        await asyncio.wait_for(self.task, timeout)


def _drive(
    app: Any, path: str, *, query: str = "", headers: dict[str, str] | None = None
) -> DrivenResponse:
    # 用局部变量（不是 `DrivenResponse` 实例本身）承接回调的副作用，这样
    # 任务可以在构造 `DrivenResponse` 之前就创建好——`task` 字段因此不需要
    # 可选类型，也不需要 `# type: ignore`（AGENTS.md 红线禁止）。
    chunks: list[bytes] = []
    start_headers: list[tuple[bytes, bytes]] = []
    status: dict[str, int] = {}
    disconnect = asyncio.Event()

    async def receive() -> dict[str, Any]:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status["status"] = message["status"]
            start_headers.extend(message.get("headers", []))
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                chunks.append(body)

    scope = _scope(path, query=query, headers=headers)
    task = asyncio.ensure_future(app(scope, receive, send))
    return DrivenResponse(
        task=task,
        chunks=chunks,
        start_headers=start_headers,
        status=status,
        disconnect=disconnect,
    )


def _parse_frame(raw: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in raw.decode().strip("\r\n").split("\r\n"):
        if not line or line.startswith(":"):
            continue  # 跳过 sse-starlette 的 keep-alive 注释帧。
        key, _, value = line.partition(": ")
        fields[key] = value
    return fields


def _event_frames(chunks: list[bytes]) -> list[dict[str, str]]:
    frames = [_parse_frame(c) for c in chunks]
    return [f for f in frames if "event" in f]


class TestStreamHttpLayer:
    async def test_unknown_session_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/sessions/does-not-exist/stream")
        assert response.status_code == 404

    async def test_response_status_and_content_type(self, api_env: ApiEnv) -> None:
        session_id = _session_id(api_env.app.state.engine)
        driven = _drive(api_env.app, f"/api/sessions/{session_id}/stream")

        assert await driven.wait_for_status() == 200
        content_type = driven.header("content-type")
        assert content_type is not None and content_type.startswith("text/event-stream")

        driven.disconnect_now()
        await driven.finish()

    async def test_frame_has_id_event_data_fields(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        append_event(
            engine, turn_id="t1", session_id=session_id, type="text", payload={"text": "hi"}
        )
        driven = _drive(api_env.app, f"/api/sessions/{session_id}/stream")

        await driven.wait_for_frames(1)
        frame = _event_frames(driven.chunks)[0]
        assert frame["id"] == "1"
        assert frame["event"] == "text"
        data = json.loads(frame["data"])
        assert data == {"text": "hi", "seq": 1}

        driven.disconnect_now()
        await driven.finish()

    async def test_transient_frame_has_no_id_line(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        bus: SessionBus = api_env.app.state.bus
        driven = _drive(api_env.app, f"/api/sessions/{session_id}/stream")

        await _wait_until(lambda: bus.subscriber_count(session_id) == 1)
        bus.publish(session_id, BusEvent(type="text_delta", payload={"text": "hi"}))
        await driven.wait_for_frames(1)

        frame = _event_frames(driven.chunks)[0]
        assert frame["event"] == "text_delta"
        assert "id" not in frame

        driven.disconnect_now()
        await driven.finish()

    async def test_last_event_id_header_used_when_after_seq_absent(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        for i in range(3):
            append_event(engine, turn_id="t1", session_id=session_id, type="text", payload={"i": i})
        driven = _drive(
            api_env.app,
            f"/api/sessions/{session_id}/stream",
            headers={"last-event-id": "2"},
        )

        await driven.wait_for_frames(1)
        frame = _event_frames(driven.chunks)[0]
        assert frame["id"] == "3"

        driven.disconnect_now()
        await driven.finish()

    async def test_after_seq_query_param_takes_precedence_over_header(
        self, api_env: ApiEnv
    ) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        for i in range(3):
            append_event(engine, turn_id="t1", session_id=session_id, type="text", payload={"i": i})
        driven = _drive(
            api_env.app,
            f"/api/sessions/{session_id}/stream",
            query="after_seq=1",
            headers={"last-event-id": "2"},
        )

        await driven.wait_for_frames(1)
        frame = _event_frames(driven.chunks)[0]
        # after_seq=1 生效（回放 seq=2 开始），说明 Last-Event-ID: 2 被忽略了
        # （否则会从 seq=3 开始）。
        assert frame["id"] == "2"

        driven.disconnect_now()
        await driven.finish()

    async def test_non_numeric_last_event_id_is_400(self, api_env: ApiEnv) -> None:
        session_id = _session_id(api_env.app.state.engine)
        driven = _drive(
            api_env.app,
            f"/api/sessions/{session_id}/stream",
            headers={"last-event-id": "not-a-number"},
        )

        assert await driven.wait_for_status() == 400
        await driven.finish()

    async def test_negative_after_seq_is_400(self, api_env: ApiEnv) -> None:
        session_id = _session_id(api_env.app.state.engine)
        driven = _drive(api_env.app, f"/api/sessions/{session_id}/stream", query="after_seq=-1")

        assert await driven.wait_for_status() == 400
        await driven.finish()

    async def test_negative_last_event_id_is_400(self, api_env: ApiEnv) -> None:
        session_id = _session_id(api_env.app.state.engine)
        driven = _drive(
            api_env.app,
            f"/api/sessions/{session_id}/stream",
            headers={"last-event-id": "-1"},
        )

        assert await driven.wait_for_status() == 400
        await driven.finish()

    async def test_real_http_disconnect_closes_subscription(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        session_id = _session_id(engine)
        bus: SessionBus = api_env.app.state.bus
        driven = _drive(api_env.app, f"/api/sessions/{session_id}/stream")

        await _wait_until(lambda: bus.subscriber_count(session_id) == 1)

        driven.disconnect_now()
        await driven.finish()

        assert bus.subscriber_count(session_id) == 0


# ---------------------------------------------------------------------------
# 端到端：真实的一轮 fake 对话
# ---------------------------------------------------------------------------


async def _project(api_env: ApiEnv) -> str:
    body = await api_env.create_project()
    return body["id"]


def _fake_profile_id(api_env: ApiEnv) -> str:
    profile = get_model_profile(api_env.app.state.engine, "fake")
    assert profile is not None
    return profile.id


async def _create_session_via_api(api_env: ApiEnv, project_id: str, stage: str = "topic") -> str:
    response = await api_env.client.post(
        f"/api/projects/{project_id}/stages/{stage}/sessions",
        json={"model_profile_id": _fake_profile_id(api_env)},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class _GatedRuntime:
    """测试专用的运行时：产出 `a`、`b` 两条文本后卡在一个由测试代码控制的
    `asyncio.Event` 上，直到测试显式 `set()` 才继续产出 `c` 并结束这一轮。

    不用 `FakeRuntime` 的 `sleep()` 步骤（真实时间的 `asyncio.sleep`）是因为
    那是**时间驱动**的——多长时间够断连接、够收够两条事件，取决于测试
    运行时的系统调度抖动，CI 慢的时候完全可能在断线前就把整轮跑完（这正是
    复审指出的 flaky 场景）。这里改成**事件驱动**：运行时物理上不可能在
    测试释放 `gate` 之前产出第三条事件，"断线时只看到前两条"这件事因此和
    墙钟时间完全无关，必然成立。
    """

    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate

    async def run_turn(self, ctx: Any) -> AsyncIterator[Any]:
        yield events.TextBlock(text="a")
        yield events.TextBlock(text="b")
        await self._gate.wait()
        yield events.TextBlock(text="c")
        yield events.TurnEnd(resume_ref=ctx.resume_ref, status="done")


async def _collect_until_terminal_turn_status(
    driven: DrivenResponse, timeout: float = 2.0
) -> list[dict[str, str]]:
    """收集帧直到出现一条状态不是 `queued`/`running` 的 `turn_status`。"""
    frames: list[dict[str, str]] = []

    async def _loop() -> None:
        seen = 0
        while True:
            while seen < len(driven.chunks):
                frame = _parse_frame(driven.chunks[seen])
                seen += 1
                if "event" not in frame:
                    continue
                frames.append(frame)
                if frame["event"] == "turn_status":
                    status = json.loads(frame["data"])["status"]
                    if status not in ("queued", "running"):
                        return
            await asyncio.sleep(0.005)

    await asyncio.wait_for(_loop(), timeout)
    return frames


class TestFakeTurnFullEventFlow:
    async def test_default_fake_script_produces_expected_wire_events(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        session_id = await _create_session_via_api(api_env, pid)
        bus: SessionBus = api_env.app.state.bus

        driven = _drive(api_env.app, f"/api/sessions/{session_id}/stream")
        await driven.wait_for_status()
        # 必须先确认真的订阅上了，才发消息——否则 "queued"/"running" 这两条
        # 瞬时状态事件可能在我们订阅之前就已经发布，读不到。
        await _wait_until(lambda: bus.subscriber_count(session_id) == 1)

        sent = await api_env.client.post(
            f"/api/sessions/{session_id}/messages", json={"text": "你好"}
        )
        assert sent.status_code == 202, sent.text
        turn_id = sent.json()["turn_id"]

        frames = await _collect_until_terminal_turn_status(driven)
        driven.disconnect_now()
        await driven.finish()
        await api_env.app.state.turn_runner.wait(turn_id)

        names = [f["event"] for f in frames]

        # TD-10：只断言真正的不变量，不绑定完整的事件顺序——runner 按 T6/T7
        # 拆分模块时，两个没有因果关系的事件谁先发布是实现细节，不应该让这
        # 条测试跟着同步改。
        #
        # 1) 这一轮恰好产出这些类型的事件、各多少次（默认 fake 脚本：说一句
        #    话、调一次工具，turn_status 有排队/运行/结束三条）。
        assert type_counts(names) == Counter(
            {
                "turn_status": 3,
                "text": 1,
                "tool_call": 1,
                "tool_result": 1,
                "workspace_changed": 1,
                "snapshot": 1,
            }
        )
        # 2) turn 生命周期本身的顺序：排队 → 运行 → 结束，这条不能松动。
        turn_statuses = [
            json.loads(f["data"])["status"] for f in frames if f["event"] == "turn_status"
        ]
        assert turn_statuses == ["queued", "running", "done"]
        # 3) turn_start 最先、turn_end 最后。
        assert names[0] == "turn_status" and turn_statuses[0] == "queued"
        assert names[-1] == "turn_status" and turn_statuses[-1] == "done"
        # 4) 因果链：text → tool_call → tool_result（说话在先，然后才是那
        #    次工具调用及其结果）。
        assert_in_order(names, "text", "tool_call", "tool_result")
        # 4.5) turn_status 变成 running 必须在第一条 text 之前（轮已经真正
        #    开始运行，模型才可能开始说话）——原来逐条比对完整事件列表时这条
        #    顺序是隐含成立的，TD-10 改成只断言相对顺序后漏掉了，这里补回来。
        status_labels = [
            f"turn_status:{json.loads(f['data'])['status']}"
            if f["event"] == "turn_status"
            else f["event"]
            for f in frames
        ]
        assert_in_order(status_labels, "turn_status:running", "text")
        # 5) workspace_changed 必须在触发它的 tool_result 之后。
        assert names.index("workspace_changed") > names.index("tool_result")
        # 6) 快照事件必须在 turn_end（最后一条 turn_status）之前。
        assert names.index("snapshot") < len(names) - 1

        transient_types = {"text_delta", "workspace_changed", "turn_status"}
        persisted_seqs: list[int] = []
        for frame in frames:
            if frame["event"] in transient_types:
                assert "id" not in frame, frame
            else:
                assert "id" in frame, frame
                persisted_seqs.append(int(frame["id"]))

        assert persisted_seqs == sorted(persisted_seqs)
        assert len(persisted_seqs) == len(set(persisted_seqs))
        assert persisted_seqs == list(range(1, len(persisted_seqs) + 1))

    async def test_disconnect_then_reconnect_with_last_event_id_no_loss_no_duplicates(
        self, api_env: ApiEnv
    ) -> None:
        from studio.agent import register_fake

        pid = await _project(api_env)
        session_id = await _create_session_via_api(api_env, pid)
        bus: SessionBus = api_env.app.state.bus

        # `_GatedRuntime` 事件驱动而不是时间驱动：产出 a、b 两条之后物理上
        # 卡在 `gate` 上，测试不 `set()` 它就绝对不会产出第三条——"断线时
        # 只看到前两条"这件事因此和墙钟时间/系统调度抖动完全无关（复审指出
        # 原先基于 `sleep()` 的写法在慢 CI 上可能整轮提前跑完，导致第二个
        # 连接永远等不到 `snapshot` 而超时）。
        gate = asyncio.Event()
        api_env.app.state.runtime_factory.register("fake", lambda: _GatedRuntime(gate))

        first = _drive(api_env.app, f"/api/sessions/{session_id}/stream")
        await first.wait_for_status()
        await _wait_until(lambda: bus.subscriber_count(session_id) == 1)

        sent = await api_env.client.post(
            f"/api/sessions/{session_id}/messages", json={"text": "你好"}
        )
        assert sent.status_code == 202, sent.text
        turn_id = sent.json()["turn_id"]

        # 运行时卡在 `gate` 上，最多也只可能先看到 a、b 这两条持久事件。
        await _wait_until(lambda: len([f for f in _event_frames(first.chunks) if "id" in f]) >= 2)
        first_seqs = [int(f["id"]) for f in _event_frames(first.chunks) if "id" in f]
        assert first_seqs == [1, 2]
        last_seen = max(first_seqs)

        first.disconnect_now()
        await first.finish()
        assert bus.subscriber_count(session_id) == 0

        second = _drive(
            api_env.app,
            f"/api/sessions/{session_id}/stream",
            headers={"last-event-id": str(last_seen)},
        )
        await second.wait_for_status()

        # 断线已经完成，现在放行运行时继续产出 c、结束这一轮。
        gate.set()

        # 一轮总共 4 条持久事件（text/text/text/snapshot）；等到快照事件出现，
        # 说明这一轮已经跑完，剩下没看到的持久事件都已经补上了。
        await _wait_until(
            lambda: any(f.get("event") == "snapshot" for f in _event_frames(second.chunks))
        )
        await api_env.app.state.turn_runner.wait(turn_id)
        second.disconnect_now()
        await second.finish()

        second_seqs = [int(f["id"]) for f in _event_frames(second.chunks) if "id" in f]
        all_seqs = first_seqs + second_seqs

        assert sorted(all_seqs) == [1, 2, 3, 4]
        assert len(all_seqs) == len(set(all_seqs))  # 不丢、不重。

        register_fake(api_env.app.state.runtime_factory)
