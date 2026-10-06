"""`sessions` 仓储：创建与查询（设计 §3.1）。

会话状态（`idle`/`running`/`interrupted`）和 `sdk_ref` 随 turn 的开始、结束
一起更新，那些写操作放在 `repo.turns` 里和 turn 行同一个事务完成。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session as DbSession

from studio.db.engine import session_scope
from studio.db.models import Session, Turn, TurnEvent
from studio.db.repo.turns import UNFINISHED_TURN_STATUSES


@dataclass(frozen=True, slots=True)
class SessionValue:
    """`sessions` 表一行的只读值对象。"""

    id: str
    project_id: str | None
    stage: str
    model_profile_id: str
    runtime: str
    sdk_ref: str | None
    status: str
    is_active: bool
    title: str | None
    subject_id: str | None = None
    """会话属于的对象：风格对话是风格 id，其余为 `None`。"""


TITLE_MAX_CHARS = 24
_SKIPPED_TITLE_MESSAGES = ("继续",)
"""「继续」是 [继续] 按钮发的固定文本，不拿来当标题。"""


def derive_title(message: str) -> str | None:
    """从用户消息得出会话标题：第一个非空行，空白折叠成一个空格，最多 `TITLE_MAX_CHARS` 个字。"""
    for line in message.splitlines():
        text = " ".join(line.split())
        if text:
            return text if len(text) <= TITLE_MAX_CHARS else text[:TITLE_MAX_CHARS] + "…"
    return None


def _auto_titles(db: DbSession, session_ids: list[str]) -> dict[str, str]:
    """没有显式标题的会话，用它第一条（非「继续」）用户消息命名；还没发过消息的没有标题。"""
    if not session_ids:
        return {}
    rows = db.execute(
        select(Turn.session_id, Turn.user_message)
        .where(Turn.session_id.in_(session_ids), Turn.user_message.not_in(_SKIPPED_TITLE_MESSAGES))
        .order_by(Turn.created_at.asc())
    ).all()
    titles: dict[str, str] = {}
    for session_id, message in rows:
        if session_id not in titles and (title := derive_title(message)):
            titles[session_id] = title
    return titles


def to_session_value(row: Session, auto_title: str | None = None) -> SessionValue:
    return SessionValue(
        id=row.id,
        project_id=row.project_id,
        stage=row.stage,
        model_profile_id=row.model_profile_id,
        runtime=row.runtime,
        sdk_ref=row.sdk_ref,
        status=row.status,
        is_active=row.is_active,
        title=row.title if row.title is not None else auto_title,
        subject_id=row.subject_id,
    )


def create_session(
    engine: Engine,
    *,
    project_id: str | None,
    stage: str,
    model_profile_id: str,
    runtime: str,
    title: str | None = None,
    subject_id: str | None = None,
) -> SessionValue:
    """新建会话并设为活动；同一项目同一阶段同一 `subject_id` 的其他会话取消活动（设计 §3.1）。"""
    with session_scope(engine) as db:
        db.execute(
            update(Session)
            .where(
                Session.project_id == project_id,
                Session.stage == stage,
                Session.subject_id == subject_id,
            )
            .values(is_active=False)
        )
        row = Session(
            project_id=project_id,
            stage=stage,
            subject_id=subject_id,
            model_profile_id=model_profile_id,
            runtime=runtime,
            title=title,
            status="idle",
            is_active=True,
        )
        db.add(row)
        db.flush()
        return to_session_value(row)


def set_session_model_if_idle(
    engine: Engine, session_id: str, model_profile_id: str
) -> SessionValue | None:
    """把会话换成另一个模型配置（M5 T7）；会话有 `queued`/`running` 的 turn 时返回 `None`，
    什么都不改。检查和更新在同一个事务里，和 `create_turn_if_session_idle` 不会交错。

    只改 `model_profile_id`：`runtime`、`sdk_ref`、`is_active` 和历史都不动——是否允许换（同
    runtime、同 provider、key 已配置）由调用方检查。会话不存在抛 `LookupError`。
    """
    with session_scope(engine) as db:
        row = db.get(Session, session_id)
        if row is None:
            raise LookupError(session_id)
        busy = db.scalars(
            select(Turn.id)
            .where(Turn.session_id == session_id, Turn.status.in_(UNFINISHED_TURN_STATUSES))
            .limit(1)
        ).first()
        if busy is not None:
            return None
        row.model_profile_id = model_profile_id
        db.flush()
        return to_session_value(row)


def set_session_title_if_unset(engine: Engine, session_id: str, title: str) -> bool:
    """给还没有标题的会话写入标题；已有标题（或会话已被删除）时什么都不改，返回 `False`。"""
    with session_scope(engine) as db:
        row = db.get(Session, session_id)
        if row is None or row.title is not None:
            return False
        row.title = title
        return True


def delete_session_if_idle(engine: Engine, session_id: str) -> bool:
    """删除一个会话及其轮次、事件；会话有 `queued`/`running` 的 turn 时返回 `False`，什么都不删。

    检查和删除在同一个事务里。删掉的是活动会话时，同范围里最后创建的一个升为活动。
    会话不存在抛 `LookupError`。
    """
    with session_scope(engine) as db:
        row = db.get(Session, session_id)
        if row is None:
            raise LookupError(session_id)
        busy = db.scalars(
            select(Turn.id)
            .where(Turn.session_id == session_id, Turn.status.in_(UNFINISHED_TURN_STATUSES))
            .limit(1)
        ).first()
        if busy is not None:
            return False
        project_id, stage, subject_id, was_active = (
            row.project_id,
            row.stage,
            row.subject_id,
            row.is_active,
        )
        db.execute(delete(TurnEvent).where(TurnEvent.session_id == session_id))
        db.execute(delete(Turn).where(Turn.session_id == session_id))
        db.execute(delete(Session).where(Session.id == session_id))
        if was_active:
            latest = db.scalars(
                select(Session)
                .where(
                    Session.project_id == project_id,
                    Session.stage == stage,
                    Session.subject_id == subject_id,
                )
                .order_by(Session.created_at.desc())
                .limit(1)
            ).first()
            if latest is not None:
                latest.is_active = True
        return True


def get_session(engine: Engine, session_id: str) -> SessionValue | None:
    """按 id 查询会话，不存在时返回 `None`。"""
    with session_scope(engine) as db:
        row = db.get(Session, session_id)
        if row is None:
            return None
        auto = _auto_titles(db, [row.id]) if row.title is None else {}
        return to_session_value(row, auto.get(row.id))


def list_sessions(
    engine: Engine, project_id: str | None, stage: str, subject_id: str | None = None
) -> list[SessionValue]:
    """某个项目某个阶段（风格对话还要同一个 `subject_id`）的全部会话，按创建时间升序。"""
    with session_scope(engine) as db:
        rows = db.scalars(
            select(Session)
            .where(
                Session.project_id == project_id,
                Session.stage == stage,
                Session.subject_id == subject_id,
            )
            .order_by(Session.created_at.asc())
        ).all()
        auto = _auto_titles(db, [row.id for row in rows if row.title is None])
        return [to_session_value(row, auto.get(row.id)) for row in rows]


def delete_project_sessions(engine: Engine, project_id: str) -> None:
    """删除项目的全部会话及其轮次、事件（删除项目时用）；没有会话时是空操作。"""
    with session_scope(engine) as db:
        session_ids = select(Session.id).where(Session.project_id == project_id)
        db.execute(delete(TurnEvent).where(TurnEvent.session_id.in_(session_ids)))
        db.execute(delete(Turn).where(Turn.session_id.in_(session_ids)))
        db.execute(delete(Session).where(Session.project_id == project_id))


def delete_subject_sessions(engine: Engine, subject_id: str) -> None:
    """删除属于某个对象（风格）的全部会话及其轮次、事件；没有会话时是空操作。"""
    with session_scope(engine) as db:
        session_ids = select(Session.id).where(Session.subject_id == subject_id)
        db.execute(delete(TurnEvent).where(TurnEvent.session_id.in_(session_ids)))
        db.execute(delete(Turn).where(Turn.session_id.in_(session_ids)))
        db.execute(delete(Session).where(Session.subject_id == subject_id))
