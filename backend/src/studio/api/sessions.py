"""`/api/projects/{id}/stages/{stage}/sessions`、`/api/sessions/{id}*`、SSE（任务简报 T8）。

会话创建（控制者裁定 1）：必须存在对应的模型配置，且 `model_profile.runtime`
已经在 `RuntimeFactory` 里注册（`enable_fake_runtime` 时的 `fake`，或
T9/T10 之后由 `main` 注册的 `claude`/`openai`）——两种情况都属于"这个会话
开局就无法运行任何一轮"，统一给 400（不是 404：模型配置本身可能存在，只是
当前进程没有启用对应运行时；调用方看到 400 就知道是配置/环境问题，而不是
"这个 id 不存在"）。

忙的语义（控制者裁定 3）：`TurnRunner.start_turn` 只在**同一会话**已有
`queued`/`running` 的 turn 时抛 `SessionBusyError`（→ 409）。项目级的串行化
（同一项目同时只跑一个 turn）由 `TurnRunner` 内部的队列承担——消息本身仍然
被接受、排队为 `queued` turn（202），不会因为项目忙就拒绝。

`POST .../continue`（控制者裁定 2）只对最近一个 turn 处于 `interrupted`/
`budget_exceeded` 的会话开放，发送固定文本"继续"；否则 409。

SSE（`GET /sessions/{id}/stream`，控制者裁定 4）：`_stream_events` 是这个
端点的核心逻辑，写成一个独立的模块级异步生成器，方便测试直接调用（不经过
HTTP 层）。顺序：先 `bus.subscribe`（同步完成的注册，返回
`agent.bus.Subscription`，见该模块文档——`close()` 是同步、幂等的，不依赖
这个订阅有没有被迭代过），再查 `seq > after_seq` 的已落库事件重放
（`id` = seq），最后转发总线的实时事件；持久事件在重放和实时交界处按 seq
去重（`last_seq` 只增不减）。瞬时事件（`text_delta`/`workspace_changed`/
`turn_status`）没有 `seq`，不去重、不重放、SSE 消息不带 `id`。

线上事件名（`WIRE_EVENT_TYPES`）直接复用 `TurnRunner`/`SessionBus` 已经在
用的 `type` 字符串，这里不做二次映射，只做一次白名单校验：出现列表之外的
`type`（理论上不应该发生，防御性检查）时跳过并记日志，不把未知类型透传给
前端。

关于测试：httpx 的 `AsyncClient` + `ASGITransport`（本项目 api 测试的标准
夹具）会在返回响应前把整个 ASGI 应用调用跑到完成才把数据交还调用方，不支持
真正的增量流式读取；但直接驱动 `app(scope, receive, send)`（自己实现
`receive`/`send`）可以拿到真实的逐块响应，`backend/tests/api/test_stream.py`
的 HTTP 层测试用这种方式验证响应头、SSE 帧格式、真实断线时的清理。详见
`docs/references/sse-starlette.md`。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Engine
from sse_starlette.sse import EventSourceResponse

from studio.agent.bus import SessionBus
from studio.agent.runner import SessionBusyError, TurnRunner
from studio.agent.runtime import RuntimeFactory, UserInput
from studio.agent.stage import WORKSPACELESS_STAGES, StageRegistry
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sessions"])

CONTINUE_TEXT = "继续"
"""控制者裁定 2：`.../continue` 固定发送这条中文文本作为用户消息。"""

WIRE_EVENT_TYPES = frozenset(
    {
        "text_delta",
        "text",
        "tool_call",
        "tool_result",
        "snapshot",
        "notice",
        "error",
        "workspace_changed",
        "turn_status",
    }
)
"""SSE 上实际会出现的全部事件名（任务简报列出的 9 种），在一个地方统一定义
（控制者裁定 6）。`_stream_events` 用它过滤——出现列表之外的 `type` 只在
`TurnRunner`/`SessionBus` 出现新 bug 时才可能发生，属于防御性检查，不是
正常路径。
"""

_RESUMABLE_TURN_STATUSES = ("interrupted", "budget_exceeded")
_CANCELLABLE_TURN_STATUSES = ("queued", "running")


def session_out(value: SessionValue) -> SessionOut:
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
    if stage in WORKSPACELESS_STAGES:  # 头脑风暴会话不属于项目，走 /api/brainstorm/sessions
        raise HTTPException(status_code=404, detail=f"未知阶段：{stage}")
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
        raise HTTPException(status_code=400, detail=f"模型配置不存在：{body.model_profile_id}")
    if not runtime_factory.has(profile.runtime):
        raise HTTPException(status_code=400, detail=f"运行时未启用：{profile.runtime}")
    session = create_session(
        engine,
        project_id=project_id,
        stage=stage,
        model_profile_id=profile.id,
        runtime=profile.runtime,
    )
    return session_out(session)


@router.get("/projects/{project_id}/stages/{stage}/sessions", response_model=list[SessionOut])
def list_sessions_endpoint(
    project_id: str, stage: str, engine: Engine = Depends(get_engine)
) -> list[SessionOut]:
    _require_project(engine, project_id)
    return [session_out(s) for s in list_sessions(engine, project_id, stage)]


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
def get_session_endpoint(session_id: str, engine: Engine = Depends(get_engine)) -> SessionDetailOut:
    session = _require_session(engine, session_id)
    turns = [_turn_out(t) for t in turns_repo.list_turns(engine, session_id)]
    return SessionDetailOut(**session_out(session).model_dump(), turns=turns)


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


def _sse_message(
    event_type: str, payload: dict[str, Any], seq: int | None
) -> dict[str, Any] | None:
    if event_type not in WIRE_EVENT_TYPES:
        logger.warning("跳过未知的 SSE 事件类型：%s", event_type)
        return None
    message: dict[str, Any] = {"event": event_type, "data": json.dumps({**payload, "seq": seq})}
    if seq is not None:
        message["id"] = str(seq)
    return message


async def _stream_events(
    engine: Engine, bus: SessionBus, session_id: str, after_seq: int
) -> AsyncGenerator[dict[str, Any], None]:
    subscription = bus.subscribe(session_id)  # 必须先订阅，再查回放范围（控制者裁定 4）。
    try:
        last_seq = after_seq
        for event in turns_repo.list_events(engine, session_id, after_seq=after_seq):
            last_seq = event.seq
            message = _sse_message(event.type, event.payload, event.seq)
            if message is not None:
                yield message

        async for bus_event in subscription:
            if bus_event.seq is not None:
                if bus_event.seq <= last_seq:
                    continue  # 回放/实时交界处的持久事件去重。
                last_seq = bus_event.seq
            message = _sse_message(bus_event.type, bus_event.payload, bus_event.seq)
            if message is not None:
                yield message
    finally:
        # 同步、幂等：不管上面有没有真正走到 `async for`（比如客户端只消费了
        # 回放就断线），都能正确摘除订阅（见 `agent.bus.Subscription` 文档）。
        subscription.close()


def _parse_after_seq(after_seq: int | None, last_event_id: str | None) -> int:
    """`after_seq` 查询参数优先于标准 `Last-Event-ID` 请求头；两者都缺省时从
    头开始。非法值（非数字、负数）→ 400，而不是让 `int()` 抛出的
    `ValueError` 变成未处理的 500。
    """
    if after_seq is not None:
        value = after_seq
    elif last_event_id is not None:
        try:
            value = int(last_event_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"非法的 Last-Event-ID：{last_event_id}"
            ) from exc
    else:
        return 0
    if value < 0:
        raise HTTPException(status_code=400, detail=f"after_seq 不能为负数：{value}")
    return value


@router.get("/sessions/{session_id}/stream")
async def stream_session_endpoint(
    session_id: str,
    request: Request,
    after_seq: int | None = Query(default=None),
    engine: Engine = Depends(get_engine),
    bus: SessionBus = Depends(get_bus),
) -> EventSourceResponse:
    _require_session(engine, session_id)
    resolved_after_seq = _parse_after_seq(after_seq, request.headers.get("last-event-id"))
    return EventSourceResponse(_stream_events(engine, bus, session_id, resolved_after_seq))
