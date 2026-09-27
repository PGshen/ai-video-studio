"""`snapshots` 仓储：插入与查询（设计 §3.1、§3.3）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, delete, select

from studio.db.engine import session_scope
from studio.db.models import Snapshot


@dataclass(frozen=True, slots=True)
class SnapshotValue:
    """`snapshots` 表一行的只读值对象。"""

    id: str
    project_id: str
    manifest: dict[str, str]
    reason: str
    turn_id: str | None
    created_at: datetime


def _to_value(row: Snapshot) -> SnapshotValue:
    return SnapshotValue(
        id=row.id,
        project_id=row.project_id,
        manifest=row.manifest,
        reason=row.reason,
        turn_id=row.turn_id,
        created_at=row.created_at,
    )


def insert_snapshot(
    engine: Engine,
    *,
    project_id: str,
    manifest: dict[str, str],
    reason: str,
    turn_id: str | None = None,
) -> SnapshotValue:
    """插入一条快照记录。"""
    with session_scope(engine) as session:
        row = Snapshot(project_id=project_id, manifest=manifest, reason=reason, turn_id=turn_id)
        session.add(row)
        session.flush()
        return _to_value(row)


def get_snapshot(engine: Engine, snapshot_id: str) -> SnapshotValue | None:
    """按 id 查询快照，不存在时返回 `None`。"""
    with session_scope(engine) as session:
        row = session.get(Snapshot, snapshot_id)
        return _to_value(row) if row is not None else None


def latest_snapshot(engine: Engine, project_id: str) -> SnapshotValue | None:
    """项目最近一份快照，不存在时返回 `None`。"""
    with session_scope(engine) as session:
        stmt = (
            select(Snapshot)
            .where(Snapshot.project_id == project_id)
            .order_by(Snapshot.created_at.desc())
            .limit(1)
        )
        row = session.scalars(stmt).one_or_none()
        return _to_value(row) if row is not None else None


def list_snapshots(engine: Engine, project_id: str) -> list[SnapshotValue]:
    """项目全部快照，按创建时间升序。"""
    with session_scope(engine) as session:
        stmt = (
            select(Snapshot)
            .where(Snapshot.project_id == project_id)
            .order_by(Snapshot.created_at.asc())
        )
        rows = session.scalars(stmt).all()
        return [_to_value(row) for row in rows]


def delete_snapshots(engine: Engine, project_id: str) -> None:
    """删除项目的全部快照行；不存在时是空操作（项目创建失败时的清理用，见
    `api.projects`）。只删 `snapshots` 表的行，不动 `BlobStore` 里的内容——
    blob 是内容寻址、可能被其他项目的快照共用，不能因为一个项目清理就删。
    """
    with session_scope(engine) as session:
        session.execute(delete(Snapshot).where(Snapshot.project_id == project_id))
