"""`turns` 与 `turn_events` 仓储（设计 §3.1、§4.4）。

`seq` 分配：在插入事件的同一个短事务里取"该会话当前最大 seq + 1"。本项目是
单进程、同步短事务（事务内没有 await），同一时刻只有一个写事务在执行，所以
max+1 不会撞号；`(session_id, seq)` 唯一索引（迁移 0002）是最后一道防线。
选它而不是内存计数器：进程重启后无需初始化，也不会和数据库状态不一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, func, select

from studio.db.engine import session_scope
from studio.db.models import Session, Turn, TurnEvent

UNFINISHED_TURN_STATUSES = ("queued", "running")

NEVER_STARTED_ERROR = "进程重启或关闭前这一轮还在排队，尚未开始运行，可以重新发送"
"""排队中的 turn 被 `interrupted` 时写进 `error`（TD-19）：`turns` 表没有"是否开始过"的列，
用这条固定文案标记，API 据此把 [继续] 变成"重发原消息"。"""


@dataclass(frozen=True, slots=True)
class TurnValue:
    """`turns` 表一行的只读值对象。"""

    id: str
    session_id: str
    user_message: str
    status: str
    start_snapshot_id: str | None
    end_snapshot_id: str | None
    usage: dict[str, Any] | None
    cost_usd: float | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    attachments: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TurnEventValue:
    """`turn_events` 表一行的只读值对象。"""

    id: str
    turn_id: str
    session_id: str
    seq: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


def _turn_value(row: Turn) -> TurnValue:
    return TurnValue(
        id=row.id,
        session_id=row.session_id,
        user_message=row.user_message,
        status=row.status,
        start_snapshot_id=row.start_snapshot_id,
        end_snapshot_id=row.end_snapshot_id,
        usage=row.usage,
        cost_usd=row.cost_usd,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        attachments=list(row.attachments or []),
    )


def _event_value(row: TurnEvent) -> TurnEventValue:
    return TurnEventValue(
        id=row.id,
        turn_id=row.turn_id,
        session_id=row.session_id,
        seq=row.seq,
        type=row.type,
        payload=row.payload,
        created_at=row.created_at,
    )


def create_turn_if_session_idle(
    engine: Engine,
    session_id: str,
    user_message: str,
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> TurnValue | None:
    """会话没有 `queued`/`running` 的 turn 时插入一个 `queued` turn；否则返回 `None`。

    检查和插入在同一个事务里完成。
    """
    with session_scope(engine) as db:
        busy = db.scalars(
            select(Turn.id)
            .where(Turn.session_id == session_id, Turn.status.in_(UNFINISHED_TURN_STATUSES))
            .limit(1)
        ).first()
        if busy is not None:
            return None
        row = Turn(
            session_id=session_id,
            user_message=user_message,
            status="queued",
            attachments=attachments or None,
        )
        db.add(row)
        db.flush()
        return _turn_value(row)


def get_turn(engine: Engine, turn_id: str) -> TurnValue | None:
    with session_scope(engine) as db:
        row = db.get(Turn, turn_id)
        return _turn_value(row) if row is not None else None


def list_turns(engine: Engine, session_id: str) -> list[TurnValue]:
    """会话的全部 turn，按创建时间升序。"""
    with session_scope(engine) as db:
        rows = db.scalars(
            select(Turn).where(Turn.session_id == session_id).order_by(Turn.created_at.asc())
        ).all()
        return [_turn_value(row) for row in rows]


def record_run_profile(
    engine: Engine, turn_id: str, *, profile_name: str, model: str, exec_mode: str | None = None
) -> None:
    """turn 开跑时记下它用的模型配置（`usage.profile_name`/`usage.model`）和执行模式
    （`usage.exec_mode`，ADR 0024；给了才记）。

    收尾时 `finish_turn` 会用完整的 usage 覆盖。这里先写一份，是因为崩溃/重启恢复
    （`interrupt_turn`）不写 usage：不先记，被中断的一轮就成了"没用过任何配置"，
    换模型提示会回溯到更早的一轮。
    """
    with session_scope(engine) as db:
        turn = db.get(Turn, turn_id)
        if turn is None:
            raise KeyError(turn_id)
        recorded: dict[str, str] = {"profile_name": profile_name, "model": model}
        if exec_mode is not None:
            recorded["exec_mode"] = exec_mode
        turn.usage = {**(turn.usage or {}), **recorded}


def previous_run_profile_name(engine: Engine, session_id: str, before_turn_id: str) -> str | None:
    """`before_turn_id` 之前最近一个记录了模型配置名（`usage.profile_name`）的 turn 所用的配置名。

    换模型提示（M5 T7）用它判断"这一轮和上一轮用的是不是同一个配置"。不看 `start_snapshot_id`
    （无项目的头脑风暴会话没有快照）；开跑前就被取消的 turn 没有 `usage`，会被跳过；M5 之前
    的旧 turn 没有 `profile_name`，同样跳过——都找不到时返回 `None`，不发提示。
    """
    with session_scope(engine) as db:
        created_at = db.scalar(select(Turn.created_at).where(Turn.id == before_turn_id))
        if created_at is None:
            return None
        # 只取 usage 一列、按时间倒序逐行读，找到第一个有配置名的就停。
        for usage in db.scalars(
            select(Turn.usage)
            .where(Turn.session_id == session_id, Turn.created_at < created_at)
            .order_by(Turn.created_at.desc())
        ):
            name = (usage or {}).get("profile_name")
            if name:
                return str(name)
    return None


def previous_turn(engine: Engine, session_id: str, before_turn_id: str) -> TurnValue | None:
    """会话中 `before_turn_id` 之前最近一个真正运行过（有 `start_snapshot_id`）且已结束的 turn。

    排队中就被取消的 turn 没有运行过，跳过它，否则前言会丢掉更早那一轮留下的
    还原路径、回滚基准等信息。
    """
    with session_scope(engine) as db:
        current = db.get(Turn, before_turn_id)
        if current is None:
            return None
        row = db.scalars(
            select(Turn)
            .where(
                Turn.session_id == session_id,
                Turn.id != before_turn_id,
                Turn.created_at <= current.created_at,
                Turn.status.not_in(UNFINISHED_TURN_STATUSES),
                Turn.start_snapshot_id.is_not(None),
            )
            .order_by(Turn.created_at.desc())
            .limit(1)
        ).first()
        return _turn_value(row) if row is not None else None


def mark_turn_running(engine: Engine, turn_id: str, *, start_snapshot_id: str | None) -> None:
    """turn → `running`，所属会话 → `running`（同一事务）。"""
    with session_scope(engine) as db:
        turn = db.get(Turn, turn_id)
        if turn is None:
            raise KeyError(turn_id)
        turn.status = "running"
        turn.start_snapshot_id = start_snapshot_id
        session = db.get(Session, turn.session_id)
        if session is not None:
            session.status = "running"


def finish_turn(
    engine: Engine,
    turn_id: str,
    *,
    status: str,
    end_snapshot_id: str | None,
    usage: dict[str, Any] | None,
    cost_usd: float | None,
    error: str | None,
    resume_ref: str | None,
) -> TurnValue:
    """写入 turn 的最终状态；会话 → `idle`，`resume_ref` 非空时更新 `sdk_ref`。"""
    with session_scope(engine) as db:
        turn = db.get(Turn, turn_id)
        if turn is None:
            raise KeyError(turn_id)
        turn.status = status
        turn.end_snapshot_id = end_snapshot_id
        turn.usage = usage
        turn.cost_usd = cost_usd
        turn.error = error
        session = db.get(Session, turn.session_id)
        if session is not None:
            session.status = "idle"
            if resume_ref is not None:
                session.sdk_ref = resume_ref
        db.flush()
        return _turn_value(turn)


def latest_turn(engine: Engine, session_id: str) -> TurnValue | None:
    """会话最近创建的一个 turn；`None` 表示会话还没有过任何 turn。

    供 `POST /sessions/{id}/cancel`、`.../continue` 判断"当前一轮"的状态用
    （任务简报 T8）。
    """
    with session_scope(engine) as db:
        row = db.scalars(
            select(Turn)
            .where(Turn.session_id == session_id)
            .order_by(Turn.created_at.desc())
            .limit(1)
        ).first()
        return _turn_value(row) if row is not None else None


def list_unfinished_turns(engine: Engine) -> list[TurnValue]:
    """所有 `queued`/`running` 的 turn（进程启动恢复用，设计 §4.4 第 8 步）。"""
    with session_scope(engine) as db:
        rows = db.scalars(
            select(Turn)
            .where(Turn.status.in_(UNFINISHED_TURN_STATUSES))
            .order_by(Turn.created_at.asc())
        ).all()
        return [_turn_value(row) for row in rows]


def interrupt_turn(
    engine: Engine, turn_id: str, *, end_snapshot_id: str | None, error: str | None = None
) -> None:
    """turn → `interrupted`，所属会话 → `interrupted`（同一事务）。"""
    with session_scope(engine) as db:
        turn = db.get(Turn, turn_id)
        if turn is None:
            raise KeyError(turn_id)
        turn.status = "interrupted"
        if error is not None:
            turn.error = error
        if end_snapshot_id is not None:
            turn.end_snapshot_id = end_snapshot_id
        session = db.get(Session, turn.session_id)
        if session is not None:
            session.status = "interrupted"


def append_event(
    engine: Engine, *, turn_id: str, session_id: str, type: str, payload: dict[str, Any]
) -> TurnEventValue:
    """插入一条持久事件，`seq` 在同一事务里按会话内 max+1 分配。"""
    with session_scope(engine) as db:
        current_max = db.scalar(
            select(func.max(TurnEvent.seq)).where(TurnEvent.session_id == session_id)
        )
        row = TurnEvent(
            turn_id=turn_id,
            session_id=session_id,
            seq=(current_max or 0) + 1,
            type=type,
            payload=payload,
        )
        db.add(row)
        db.flush()
        return _event_value(row)


def list_events(engine: Engine, session_id: str, *, after_seq: int = 0) -> list[TurnEventValue]:
    """会话中 `seq > after_seq` 的事件，按 seq 升序（SSE 回放用）。"""
    with session_scope(engine) as db:
        rows = db.scalars(
            select(TurnEvent)
            .where(TurnEvent.session_id == session_id, TurnEvent.seq > after_seq)
            .order_by(TurnEvent.seq.asc())
        ).all()
        return [_event_value(row) for row in rows]


def list_turn_events(engine: Engine, turn_id: str) -> list[TurnEventValue]:
    """一个 turn 的全部事件，按 seq 升序。"""
    with session_scope(engine) as db:
        rows = db.scalars(
            select(TurnEvent).where(TurnEvent.turn_id == turn_id).order_by(TurnEvent.seq.asc())
        ).all()
        return [_event_value(row) for row in rows]
