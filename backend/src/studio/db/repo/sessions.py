"""`sessions` 仓储：创建与查询（设计 §3.1）。

会话状态（`idle`/`running`/`interrupted`）和 `sdk_ref` 随 turn 的开始、结束
一起更新，那些写操作放在 `repo.turns` 里和 turn 行同一个事务完成。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, update

from studio.db.engine import session_scope
from studio.db.models import Session


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


def get_session(engine: Engine, session_id: str) -> SessionValue | None:
    """按 id 查询会话，不存在时返回 `None`。"""
    with session_scope(engine) as db:
        row = db.get(Session, session_id)
        return to_session_value(row) if row is not None else None
