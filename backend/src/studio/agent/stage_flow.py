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


def _artifacts_of(manifest: Manifest, definition: StageDefinition) -> Manifest:
    """清单里属于该阶段产物目录的那部分（快照是整项目的，判断内容变化只看产物目录）。"""
    prefixes = tuple(f"{directory.rstrip('/')}/" for directory in definition.artifact_dirs())
    return {path: sha for path, sha in manifest.items() if path.startswith(prefixes)}


def _upstream_artifacts_changed(
    engine: Engine, upstream: StageDefinition, based_on_id: str | None, new: Manifest
) -> bool:
    """下游所基于的快照与新定稿快照，在上游产物目录下是否不同（TD-6）。

    所基于的快照缺失（从未记录或已被清理）时保守地按"有变化"处理。
    """
    based_on = get_snapshot(engine, based_on_id) if based_on_id is not None else None
    if based_on is None:
        return True
    return _artifacts_of(based_on.manifest, upstream) != _artifacts_of(new, upstream)


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
            changed = _upstream_artifacts_changed(
                engine, registry.get(stage), row.based_on_snapshot_id, snapshot.manifest
            )
            if changed:
                update_stage(engine, project_id, row.stage, status="stale")
            elif row.status == "stale":
                # 上游产物已经改回下游所基于的样子：下游没有过期内容了。
                update_stage(engine, project_id, row.stage, status="active")
    return finalized


def reopen(engine: Engine, project_id: str, stage: str) -> StageValue:
    """重新打开已定稿阶段：状态回到 `active`；下游在它重新定稿前仍读旧定稿版本。"""
    current = _require_stage(engine, project_id, stage)
    if current.status != "finalized":
        raise StageFlowError(f"阶段 {stage} 当前为 {current.status}，只有已定稿阶段能重新打开")
    return update_stage(engine, project_id, stage, status="active")


def after_turn_done(
    engine: Engine, project_id: str, stage: str, used_upstream: dict[str, str | None]
) -> None:
    """下游一轮成功结束后，把 `based_on_snapshot_id` 更新为**本轮开始时**物化的
    上游定稿（`used_upstream`，来自 `upstream_snapshot_ids`），而不是轮末的最新
    定稿——轮中上游又定稿了的话，agent 并没有看到新版本。只有用到的版本仍是
    上游当前定稿时，`stale` 才回到 `active`。

    M1 每个阶段最多一个上游；有多个上游时取按上游顺序的第一个已定稿版本。
    """
    current = get_stage(engine, project_id, stage)
    used = next(((name, sid) for name, sid in used_upstream.items() if sid is not None), None)
    if current is None or used is None:
        return
    name, snapshot_id = used
    upstream = get_stage(engine, project_id, name)
    up_to_date = upstream is not None and upstream.finalized_snapshot_id == snapshot_id
    status = "active" if current.status == "stale" and up_to_date else None
    if snapshot_id == current.based_on_snapshot_id and status is None:
        return
    update_stage(engine, project_id, stage, status=status, based_on_snapshot_id=snapshot_id)


def upstream_snapshot_ids(
    engine: Engine, project_id: str, stage: StageDefinition
) -> dict[str, str | None]:
    """每个上游阶段当前的 `finalized_snapshot_id`（未定稿为 `None`）。"""
    ids: dict[str, str | None] = {}
    for name in stage.upstream_stages():
        row = get_stage(engine, project_id, name)
        ids[name] = row.finalized_snapshot_id if row is not None else None
    return ids


def manifests_of(engine: Engine, snapshot_ids: dict[str, str | None]) -> dict[str, Manifest | None]:
    """把 `{阶段: 快照 id}` 换成 `{阶段: 清单}`，供 `materialize_upstream` 使用。"""
    sources: dict[str, Manifest | None] = {}
    for name, snapshot_id in snapshot_ids.items():
        snapshot = get_snapshot(engine, snapshot_id) if snapshot_id is not None else None
        sources[name] = snapshot.manifest if snapshot is not None else None
    return sources


def upstream_sources(
    engine: Engine, project_id: str, stage: StageDefinition
) -> dict[str, Manifest | None]:
    """每个上游阶段的定稿快照清单（未定稿为 `None`）。"""
    return manifests_of(engine, upstream_snapshot_ids(engine, project_id, stage))
