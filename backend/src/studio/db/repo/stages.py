"""`project_stages` 仓储（设计 §3.1、§5.4）。

状态流转规则（定稿、重新打开、stale）不在这里，在 `studio.agent.stage_flow`；
本模块只提供行级读写。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from studio.db.engine import session_scope
from studio.db.models import ProjectStage


@dataclass(frozen=True, slots=True)
class StageValue:
    """`project_stages` 表一行的只读值对象。"""

    project_id: str
    stage: str
    status: str
    finalized_snapshot_id: str | None
    based_on_snapshot_id: str | None
    finalized_at: datetime | None


def _to_value(row: ProjectStage) -> StageValue:
    return StageValue(
        project_id=row.project_id,
        stage=row.stage,
        status=row.status,
        finalized_snapshot_id=row.finalized_snapshot_id,
        based_on_snapshot_id=row.based_on_snapshot_id,
        finalized_at=row.finalized_at,
    )


def create_stage(engine: Engine, *, project_id: str, stage: str, status: str) -> StageValue:
    with session_scope(engine) as db:
        row = ProjectStage(project_id=project_id, stage=stage, status=status)
        db.add(row)
        db.flush()
        return _to_value(row)


def _get_row(db: Session, project_id: str, stage: str) -> ProjectStage | None:
    return db.scalars(
        select(ProjectStage).where(
            ProjectStage.project_id == project_id, ProjectStage.stage == stage
        )
    ).first()


def get_stage(engine: Engine, project_id: str, stage: str) -> StageValue | None:
    with session_scope(engine) as db:
        row = _get_row(db, project_id, stage)
        return _to_value(row) if row is not None else None


def list_stages(engine: Engine, project_id: str) -> list[StageValue]:
    """项目的全部阶段行，按创建顺序。"""
    with session_scope(engine) as db:
        rows = db.scalars(
            select(ProjectStage)
            .where(ProjectStage.project_id == project_id)
            .order_by(ProjectStage.created_at.asc())
        ).all()
        return [_to_value(row) for row in rows]


def update_stage(
    engine: Engine,
    project_id: str,
    stage: str,
    *,
    status: str | None = None,
    finalized_snapshot_id: str | None = None,
    based_on_snapshot_id: str | None = None,
    finalized_at: datetime | None = None,
) -> StageValue:
    """更新阶段行；参数为 `None` 表示该字段不变。"""
    with session_scope(engine) as db:
        row = _get_row(db, project_id, stage)
        if row is None:
            raise KeyError(f"{project_id}/{stage}")
        if status is not None:
            row.status = status
        if finalized_snapshot_id is not None:
            row.finalized_snapshot_id = finalized_snapshot_id
        if based_on_snapshot_id is not None:
            row.based_on_snapshot_id = based_on_snapshot_id
        if finalized_at is not None:
            row.finalized_at = finalized_at
        db.flush()
        return _to_value(row)
