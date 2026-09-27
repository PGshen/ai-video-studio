"""`/api/projects/{id}/snapshots*`（任务简报 T7）。

项目级串行（I4）：凡是"先查 `is_project_busy` 再写工作区"的端点都写成
`async def`，在事件循环线程上执行，检查与写入之间不 `await`——`TurnRunner`
也在事件循环上改 `_running`、调度排队的 turn，两者不会交错。同步 `def` 端点
会跑在线程池里，出现检查通过后被调度器插队的竞态。代价是这些端点里的
短小同步 IO（SQLite、写文件、回滚）会占用事件循环片刻，单人本地可接受。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from studio.agent.runner import TurnRunner
from studio.api.deps import get_blobs, get_engine, get_turn_runner
from studio.api.schemas import ModifiedFileOut, SnapshotDiffOut, SnapshotOut
from studio.db.repo.projects import get_project
from studio.db.repo.snapshots import SnapshotValue, get_snapshot, list_snapshots
from studio.workspace import BlobStore, diff, rollback

router = APIRouter(prefix="/api", tags=["snapshots"])


def _require_project(engine: Engine, project_id: str) -> None:
    if get_project(engine, project_id) is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")


def _snapshot_out(value: SnapshotValue) -> SnapshotOut:
    return SnapshotOut(
        id=value.id, reason=value.reason, turn_id=value.turn_id, created_at=value.created_at
    )


def _require_snapshot(engine: Engine, project_id: str, snapshot_id: str) -> SnapshotValue:
    snapshot = get_snapshot(engine, snapshot_id)
    if snapshot is None or snapshot.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"快照不存在：{snapshot_id}")
    return snapshot


@router.get("/projects/{project_id}/snapshots", response_model=list[SnapshotOut])
def list_snapshots_endpoint(
    project_id: str, engine: Engine = Depends(get_engine)
) -> list[SnapshotOut]:
    _require_project(engine, project_id)
    return [_snapshot_out(s) for s in list_snapshots(engine, project_id)]


@router.get("/projects/{project_id}/snapshots/diff", response_model=SnapshotDiffOut)
def diff_snapshots_endpoint(
    project_id: str,
    from_id: str = Query(..., alias="from"),
    to_id: str = Query(..., alias="to"),
    engine: Engine = Depends(get_engine),
    blobs: BlobStore = Depends(get_blobs),
) -> SnapshotDiffOut:
    _require_project(engine, project_id)
    old = _require_snapshot(engine, project_id, from_id)
    new = _require_snapshot(engine, project_id, to_id)
    result = diff(old.manifest, new.manifest, blobs)
    return SnapshotDiffOut(
        added=result.added,
        removed=result.removed,
        modified=[
            ModifiedFileOut(path=item.path, text_diff=item.text_diff) for item in result.modified
        ],
    )


@router.post("/projects/{project_id}/snapshots/{snapshot_id}/rollback", response_model=SnapshotOut)
async def rollback_endpoint(
    project_id: str,
    snapshot_id: str,
    engine: Engine = Depends(get_engine),
    blobs: BlobStore = Depends(get_blobs),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> SnapshotOut:
    _require_project(engine, project_id)
    _require_snapshot(engine, project_id, snapshot_id)
    if turn_runner.is_project_busy(project_id):
        raise HTTPException(status_code=409, detail="项目正在运行中的一轮，请稍后再试")
    result = rollback(engine, blobs, project_id, snapshot_id)
    return SnapshotOut(
        id=result.id, reason=result.reason, turn_id=result.turn_id, created_at=result.created_at
    )
