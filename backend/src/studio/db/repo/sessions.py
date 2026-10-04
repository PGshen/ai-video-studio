"""`sessions` 仓储：创建与查询（设计 §3.1）。

会话状态（`idle`/`running`/`interrupted`）和 `sdk_ref` 随 turn 的开始、结束
一起更新，那些写操作放在 `repo.turns` 里和 turn 行同一个事务完成。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, delete, select, update

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


def to_session_value(row: Session) -> SessionValue:
    return SessionValue(
        id=row.id,
        project_id=row.project_id,
        stage=row.stage,
        model_profile_id=row.model_profile_id,
        runtime=row.runtime,
        sdk_ref=row.sdk_ref,
        status=row.status,
        is_active=row.is_active,
        title=row.title,
    )


def create_session(
    engine: Engine,
    *,
    project_id: str | None,
    stage: str,
    model_profile_id: str,
    runtime: str,
    title: str | None = None,
) -> SessionValue:
    """新建会话并设为活动；同一项目同一阶段的其他会话取消活动（设计 §3.1 说明）。"""
    with session_scope(engine) as db:
        db.execute(
            update(Session)
            .where(Session.project_id == project_id, Session.stage == stage)
            .values(is_active=False)
        )
        row = Session(
            project_id=project_id,
            stage=stage,
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


def get_session(engine: Engine, session_id: str) -> SessionValue | None:
    """按 id 查询会话，不存在时返回 `None`。"""
    with session_scope(engine) as db:
        row = db.get(Session, session_id)
        return to_session_value(row) if row is not None else None


def list_sessions(engine: Engine, project_id: str | None, stage: str) -> list[SessionValue]:
    """某个项目某个阶段的全部会话，按创建时间升序（`GET .../sessions` 用）。"""
    with session_scope(engine) as db:
        rows = db.scalars(
            select(Session)
            .where(Session.project_id == project_id, Session.stage == stage)
            .order_by(Session.created_at.asc())
        ).all()
        return [to_session_value(row) for row in rows]


def delete_project_sessions(engine: Engine, project_id: str) -> None:
    """删除项目的全部会话及其轮次、事件（删除项目时用）；没有会话时是空操作。"""
    with session_scope(engine) as db:
        session_ids = select(Session.id).where(Session.project_id == project_id)
        db.execute(delete(TurnEvent).where(TurnEvent.session_id.in_(session_ids)))
        db.execute(delete(Turn).where(Turn.session_id.in_(session_ids)))
        db.execute(delete(Session).where(Session.project_id == project_id))
