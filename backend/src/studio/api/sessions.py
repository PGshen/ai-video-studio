"""`/api/projects/{id}/stages/{stage}/sessions`、`/api/sessions/{id}*`、SSE（任务简报 T8）。

会话创建（控制者裁定 1）：`model_profile.runtime` 必须已经在 `RuntimeFactory`
里注册（`enable_fake_runtime` 时的 `fake`，或 T9/T10 之后由 `main` 注册的
`claude`/`openai`），否则新会话开局即无法运行任何一轮，直接 400。

忙的语义（控制者裁定 3）：`TurnRunner.start_turn` 只在**同一会话**已有
`queued`/`running` 的 turn 时抛 `SessionBusyError`（→ 409）。项目级的串行化
（同一项目同时只跑一个 turn）由 `TurnRunner` 内部的队列承担——消息本身仍然
被接受、排队为 `queued` turn（202），不会因为项目忙就拒绝。

`POST .../continue`（控制者裁定 2）只对最近一个 turn 处于 `interrupted`/
`budget_exceeded` 的会话开放，发送固定文本"继续"；否则 409。

SSE（`GET /sessions/{id}/stream`，控制者裁定 4）：`_stream_events` 是这个
端点的核心逻辑，刻意写成一个独立的模块级异步生成器，方便测试直接调用
（不经过 HTTP 层）——httpx 的 `ASGITransport` 会在返回响应前把整个 ASGI 应用
调用跑到完成（参见 `docs/references/sse-starlette.md` 的实测记录），对于
一个不会自己结束的 SSE 流，这意味着经 HTTP 层做"收到几条事件后断开重连"
的用例在测试里永远拿不到任何中间数据，只能超时；因此这类断线重连场景的
测试直接调用 `_stream_events`。

顺序：先 `bus.subscribe`（同步完成的注册，见 `agent.bus` 模块文档），再查
`seq > after_seq` 的已落库事件重放（`id` = seq），最后转发总线的实时事件；
持久事件在重放和实时交界处按 seq 去重（`last_seq` 只增不减）。瞬时事件
（`text_delta`/`workspace_changed`/`turn_status`）没有 `seq`，不去重、不重放、
SSE 消息不带 `id`。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Engine
from sse_starlette.sse import EventSourceResponse

from studio.agent.bus import BusEvent, SessionBus
from studio.agent.runner import SessionBusyError, TurnRunner
from studio.agent.runtime import RuntimeFactory, UserInput
from studio.agent.stage import StageRegistry
from studio.api.deps import get_bus, get_engine, get_registry, get_runtime_factory, get_turn_runner
from studio.api.schemas import (
    MessageCreate,
    SessionCreate,
    SessionDetailOut,
    SessionOut,
    TurnAccepted,
    TurnOut,
)
from studio.db.repo import turns as turns_repo
from studio.db.repo.profiles import get_model_profile_by_id
from studio.db.repo.projects import get_project
from studio.db.repo.sessions import SessionValue, create_session, get_session, list_sessions
from studio.db.repo.turns import TurnValue

router = APIRouter(prefix="/api", tags=["sessions"])

CONTINUE_TEXT = "继续"
"""控制者裁定 2：`.../continue` 固定发送这条中文文本作为用户消息。"""

_RESUMABLE_TURN_STATUSES = ("interrupted", "budget_exceeded")
_CANCELLABLE_TURN_STATUSES = ("queued", "running")


def _session_out(value: SessionValue) -> SessionOut:
    return SessionOut(
        id=value.id,
        project_id=value.project_id,
        stage=value.stage,
        model_profile_id=value.model_profile_id,
        runtime=value.runtime,
        sdk_ref=value.sdk_ref,
        status=value.status,
        is_active=value.is_active,
        title=value.title,
    )


def _turn_out(value: TurnValue) -> TurnOut:
    return TurnOut(
        id=value.id,
        session_id=value.session_id,
        user_message=value.user_message,
        status=value.status,
        start_snapshot_id=value.start_snapshot_id,
        end_snapshot_id=value.end_snapshot_id,
        usage=value.usage,
        cost_usd=value.cost_usd,
        error=value.error,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _require_project(engine: Engine, project_id: str) -> None:
    if get_project(engine, project_id) is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")


def _require_stage(stage: str, registry: StageRegistry) -> None:
    try:
        registry.get(stage)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"未知阶段：{stage}") from exc


def _require_session(engine: Engine, session_id: str) -> SessionValue:
    session = get_session(engine, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
    return session


@router.post(
    "/projects/{project_id}/stages/{stage}/sessions", response_model=SessionOut, status_code=201
)
def create_session_endpoint(
    project_id: str,
    stage: str,
    body: SessionCreate,
    engine: Engine = Depends(get_engine),
    registry: StageRegistry = Depends(get_registry),
    runtime_factory: RuntimeFactory = Depends(get_runtime_factory),
) -> SessionOut:
    _require_project(engine, project_id)
    _require_stage(stage, registry)
    profile = get_model_profile_by_id(engine, body.model_profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"模型配置不存在：{body.model_profile_id}")
    if not runtime_factory.has(profile.runtime):
        raise HTTPException(status_code=400, detail=f"运行时未启用：{profile.runtime}")
    session = create_session(
        engine,
        project_id=project_id,
        stage=stage,
        model_profile_id=profile.id,
        runtime=profile.runtime,
    )
    return _session_out(session)


@router.get("/projects/{project_id}/stages/{stage}/sessions", response_model=list[SessionOut])
def list_sessions_endpoint(
    project_id: str, stage: str, engine: Engine = Depends(get_engine)
) -> list[SessionOut]:
    _require_project(engine, project_id)
    return [_session_out(s) for s in list_sessions(engine, project_id, stage)]


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
def get_session_endpoint(session_id: str, engine: Engine = Depends(get_engine)) -> SessionDetailOut:
    session = _require_session(engine, session_id)
    turns = [_turn_out(t) for t in turns_repo.list_turns(engine, session_id)]
    return SessionDetailOut(**_session_out(session).model_dump(), turns=turns)


@router.post("/sessions/{session_id}/messages", response_model=TurnAccepted, status_code=202)
async def send_message_endpoint(
    session_id: str,
    body: MessageCreate,
    engine: Engine = Depends(get_engine),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> TurnAccepted:
    _require_session(engine, session_id)
    try:
        turn_id = await turn_runner.start_turn(session_id, UserInput(text=body.text))
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail="会话正忙，请等待当前一轮结束") from exc
    return TurnAccepted(turn_id=turn_id)


@router.post("/sessions/{session_id}/cancel", response_model=TurnAccepted, status_code=202)
async def cancel_session_endpoint(
    session_id: str,
    engine: Engine = Depends(get_engine),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> TurnAccepted:
    _require_session(engine, session_id)
    turn = turns_repo.latest_turn(engine, session_id)
    if turn is None or turn.status not in _CANCELLABLE_TURN_STATUSES:
        raise HTTPException(status_code=409, detail="当前没有正在运行的一轮可以取消")
    if not turn_runner.cancel(turn.id):
        raise HTTPException(status_code=409, detail="当前没有正在运行的一轮可以取消")
    return TurnAccepted(turn_id=turn.id)


@router.post("/sessions/{session_id}/continue", response_model=TurnAccepted, status_code=202)
async def continue_session_endpoint(
    session_id: str,
    engine: Engine = Depends(get_engine),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> TurnAccepted:
    _require_session(engine, session_id)
    turn = turns_repo.latest_turn(engine, session_id)
    if turn is None or turn.status not in _RESUMABLE_TURN_STATUSES:
        raise HTTPException(status_code=409, detail="当前会话没有可以继续的一轮")
    try:
        turn_id = await turn_runner.start_turn(session_id, UserInput(text=CONTINUE_TEXT))
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail="会话正忙，请等待当前一轮结束") from exc
    return TurnAccepted(turn_id=turn_id)


def _sse_message(event_type: str, payload: dict[str, Any], seq: int | None) -> dict[str, Any]:
    message: dict[str, Any] = {"event": event_type, "data": json.dumps({**payload, "seq": seq})}
    if seq is not None:
        message["id"] = str(seq)
    return message


async def _stream_events(
    engine: Engine, bus: SessionBus, session_id: str, after_seq: int
) -> AsyncGenerator[dict[str, Any], None]:
    subscription = bus.subscribe(session_id)  # 必须先订阅，再查回放范围（控制者裁定 4）。
    # 立刻在后台把 `subscription` 这个异步生成器"跑起来"（`ensure_future` 调度
    # 它的第一步，比如 `_pump` 内部真正挂起在 `await _has_data.wait()`）。
    # 原因（审查后修复）：Python 的异步生成器完全惰性——如果这一轮客户端只
    # 消费了回放里的历史事件就断线，`async for bus_event in subscription`
    # 这一行永远不会执行，`subscription` 也就从未真正启动过；这时对一个
    # "冷"的（从未 `__anext__` 过的）异步生成器调用 `aclose()` 是纯粹的空
    # 操作，不会跑它的 `finally`（`SessionBus._pump` 里把订阅者从列表移除的
    # 那段代码），订阅会永远留在 `SessionBus` 里（评审关注点 2 明确要求避免
    # 的订阅者泄漏）。提前把它排进事件循环，能保证不管回放阶段消费了几条、
    # 有没有真正走到实时转发，`finally` 里的 `live_next.cancel()` 都能命中
    # 一个已经真正开始执行、挂起在总线等待点上的任务，从而正确触发取消订阅。
    live_next: asyncio.Task[BusEvent] = asyncio.ensure_future(subscription.__anext__())
    try:
        # `timeout=0` 只给 `live_next` 一次调度机会：足够让它推进到自己真正的
        # 挂起点（`_pump` 内部 `await _has_data.wait()`），但不会等它真的产出
        # 一个事件；`shield` 防止这里的超时连带取消 `live_next` 本身。这样不管
        # 下面回放阶段消费了几条就断线，`finally` 里 `live_next.cancel()` 命中
        # 的都是一个已经真正开始执行的任务，取消才能传播到 `_pump` 的
        # `finally`（这段必须写在 `try` 里面：万一取消恰好发生在这一步本身，
        # 也要能落到下面的 `finally` 做清理，而不是整段被跳过）。
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(live_next), timeout=0)

        last_seq = after_seq
        for event in turns_repo.list_events(engine, session_id, after_seq=after_seq):
            last_seq = event.seq
            yield _sse_message(event.type, event.payload, event.seq)

        while True:
            bus_event = await live_next
            live_next = asyncio.ensure_future(subscription.__anext__())
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(live_next), timeout=0)
            if bus_event.seq is not None:
                if bus_event.seq <= last_seq:
                    continue  # 回放/实时交界处的持久事件去重。
                last_seq = bus_event.seq
            yield _sse_message(bus_event.type, bus_event.payload, bus_event.seq)
    finally:
        live_next.cancel()
        with contextlib.suppress(BaseException):
            await live_next
        await subscription.aclose()


@router.get("/sessions/{session_id}/stream")
async def stream_session_endpoint(
    session_id: str,
    request: Request,
    after_seq: int | None = Query(default=None),
    engine: Engine = Depends(get_engine),
    bus: SessionBus = Depends(get_bus),
) -> EventSourceResponse:
    _require_session(engine, session_id)
    if after_seq is None:
        last_event_id = request.headers.get("last-event-id")
        after_seq = int(last_event_id) if last_event_id is not None else 0
    return EventSourceResponse(_stream_events(engine, bus, session_id, after_seq))
