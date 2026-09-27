"""阶段流转的通用部分（设计 §5.4）：定稿、重新打开、下游 stale 标记与恢复。

与具体阶段无关：上下游关系只从 `StageDefinition.upstream_stages()` 读取。
`project_stages` 的状态：`locked` → `active` ⇄ `finalized`，上游重新定稿且
内容变化时下游变为 `stale`，下游下一轮成功结束后回到 `active`。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine

from studio.agent.stage import StageDefinition, StageRegistry
from studio.db.repo.snapshots import get_snapshot
from studio.db.repo.stages import StageValue, get_stage, list_stages, update_stage
from studio.workspace import BlobStore, Manifest, create_snapshot


class StageFlowError(ValueError):
    """非法的阶段流转（例如定稿 `locked` 阶段、重新打开未定稿阶段）。"""


def _require_stage(engine: Engine, project_id: str, stage: str) -> StageValue:
    value = get_stage(engine, project_id, stage)
    if value is None:
        raise StageFlowError(f"项目 {project_id} 没有阶段 {stage}")
    return value


def _downstream_of(
    engine: Engine, registry: StageRegistry, project_id: str, stage: str
) -> list[StageValue]:
    downstream: list[StageValue] = []
    for row in list_stages(engine, project_id):
        try:
            definition = registry.get(row.stage)
        except KeyError:
            continue
        if stage in definition.upstream_stages():
            downstream.append(row)
    return downstream


def finalize(
    engine: Engine, blobs: BlobStore, registry: StageRegistry, project_id: str, stage: str
) -> StageValue:
    """定稿：以当前工作区快照为定稿版本，解锁或标记下游。

    先调用 `create_snapshot`（内容未变时返回最近一份快照），保证用户未快照的
    手动修改也进入定稿版本；`finalized_snapshot_id` 因此总是"最新快照"。
    """
    current = _require_stage(engine, project_id, stage)
    if current.status == "locked":
        raise StageFlowError(f"阶段 {stage} 尚未解锁，不能定稿")

    snapshot = create_snapshot(engine, blobs, project_id, reason="user_edit")
    finalized = update_stage(
        engine,
        project_id,
        stage,
        status="finalized",
        finalized_snapshot_id=snapshot.id,
        finalized_at=datetime.now(UTC),
    )

    for row in _downstream_of(engine, registry, project_id, stage):
        if row.status == "locked":
            update_stage(
                engine, project_id, row.stage, status="active", based_on_snapshot_id=snapshot.id
            )
        elif row.based_on_snapshot_id != snapshot.id:
            update_stage(engine, project_id, row.stage, status="stale")
    return finalized


def reopen(engine: Engine, project_id: str, stage: str) -> StageValue:
    """重新打开已定稿阶段：状态回到 `active`；下游在它重新定稿前仍读旧定稿版本。"""
    current = _require_stage(engine, project_id, stage)
    if current.status != "finalized":
        raise StageFlowError(f"阶段 {stage} 当前为 {current.status}，只有已定稿阶段能重新打开")
    return update_stage(engine, project_id, stage, status="active")


def after_turn_done(engine: Engine, registry: StageRegistry, project_id: str, stage: str) -> None:
    """下游一轮成功结束后：`based_on_snapshot_id` 更新为上游当前定稿，`stale` → `active`。

    M1 的每个阶段最多一个上游；有多个上游时取最近定稿的那一个。
    """
    current = get_stage(engine, project_id, stage)
    if current is None:
        return
    upstream_rows = [
        row
        for name in registry.get(stage).upstream_stages()
        if (row := get_stage(engine, project_id, name)) is not None
        and row.finalized_snapshot_id is not None
    ]
    if not upstream_rows:
        return
    latest = max(upstream_rows, key=lambda row: row.finalized_at or datetime.min)
    status = "active" if current.status == "stale" else None
    if latest.finalized_snapshot_id == current.based_on_snapshot_id and status is None:
        return
    update_stage(
        engine,
        project_id,
        stage,
        status=status,
        based_on_snapshot_id=latest.finalized_snapshot_id,
    )


def upstream_sources(
    engine: Engine, project_id: str, stage: StageDefinition
) -> dict[str, Manifest | None]:
    """每个上游阶段的定稿快照清单（未定稿为 `None`），供 `materialize_upstream` 使用。"""
    sources: dict[str, Manifest | None] = {}
    for name in stage.upstream_stages():
        row = get_stage(engine, project_id, name)
        snapshot_id = row.finalized_snapshot_id if row is not None else None
        snapshot = get_snapshot(engine, snapshot_id) if snapshot_id is not None else None
        sources[name] = snapshot.manifest if snapshot is not None else None
    return sources
