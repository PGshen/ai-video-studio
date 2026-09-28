"""`jobs` 仓储：SQLite 任务队列的创建、领取、心跳、进度、完成/失败、查询。

领取语义（`claim_next`）只保证同进程内不重复领取，不做跨进程分布式锁——
本计划只跑单个 worker 进程，见决策记录 D2。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select

from studio.db.engine import session_scope
from studio.db.models import Job


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class JobValue:
    """`jobs` 表一行的只读值对象。"""

    id: str
    type: str
    project_id: str
    payload: dict[str, Any] | None
    status: str
    progress: float
    heartbeat_at: datetime | None
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


def _to_value(row: Job) -> JobValue:
    return JobValue(
        id=row.id,
        type=row.type,
        project_id=row.project_id,
        payload=row.payload,
        status=row.status,
        progress=row.progress,
        heartbeat_at=row.heartbeat_at,
        result=row.result,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_job(
    engine: Engine, *, type: str, project_id: str, payload: dict[str, Any] | None = None
) -> JobValue:
    """创建一条 `queued` 任务。"""
    with session_scope(engine) as db:
        row = Job(type=type, project_id=project_id, payload=payload, status="queued")
        db.add(row)
        db.flush()
        return _to_value(row)


def claim_next(engine: Engine, *, type: str) -> JobValue | None:
    """领取最早创建的一条 `queued` 任务，原子地标记为 `running`；队列空时返回 `None`。"""
    with session_scope(engine) as db:
        row = db.scalars(
            select(Job)
            .where(Job.type == type, Job.status == "queued")
            .order_by(Job.created_at.asc())
            .limit(1)
        ).first()
        if row is None:
            return None
        row.status = "running"
        row.heartbeat_at = _utcnow()
        db.flush()
        return _to_value(row)


def heartbeat(engine: Engine, job_id: str) -> None:
    """更新任务的心跳时间。"""
    with session_scope(engine) as db:
        row = db.get(Job, job_id)
        if row is None:
            raise KeyError(job_id)
        row.heartbeat_at = _utcnow()


def update_progress(engine: Engine, job_id: str, progress: float) -> None:
    with session_scope(engine) as db:
        row = db.get(Job, job_id)
        if row is None:
            raise KeyError(job_id)
        row.progress = progress


def complete(engine: Engine, job_id: str, *, result: dict[str, Any]) -> JobValue:
    with session_scope(engine) as db:
        row = db.get(Job, job_id)
        if row is None:
            raise KeyError(job_id)
        row.status = "done"
        row.progress = 1.0
        row.result = result
        db.flush()
        return _to_value(row)


def fail(engine: Engine, job_id: str, *, error: str) -> JobValue:
    with session_scope(engine) as db:
        row = db.get(Job, job_id)
        if row is None:
            raise KeyError(job_id)
        row.status = "failed"
        row.error = error
        db.flush()
        return _to_value(row)


def get_job(engine: Engine, job_id: str) -> JobValue | None:
    with session_scope(engine) as db:
        row = db.get(Job, job_id)
        return _to_value(row) if row is not None else None


def list_jobs(engine: Engine, project_id: str, type: str | None = None) -> list[JobValue]:
    with session_scope(engine) as db:
        stmt = select(Job).where(Job.project_id == project_id)
        if type is not None:
            stmt = stmt.where(Job.type == type)
        stmt = stmt.order_by(Job.created_at.asc())
        rows = db.scalars(stmt).all()
        return [_to_value(row) for row in rows]


def reap_stale_running(
    engine: Engine, *, type: str, heartbeat_timeout_seconds: float
) -> list[JobValue]:
    """把心跳过期的 `running` 任务标记 `failed`（worker 启动时调用）。"""
    with session_scope(engine) as db:
        threshold = _utcnow() - timedelta(seconds=heartbeat_timeout_seconds)
        rows = db.scalars(
            select(Job).where(
                Job.type == type,
                Job.status == "running",
                Job.heartbeat_at.is_not(None),
                Job.heartbeat_at < threshold,
            )
        ).all()
        for row in rows:
            row.status = "failed"
            row.error = "worker 心跳超时（可能是进程崩溃）"
        db.flush()
        return [_to_value(row) for row in rows]
