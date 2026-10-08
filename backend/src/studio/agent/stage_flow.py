"""阶段流转的通用部分（设计 §5.4）：定稿、重新打开、下游 stale 标记与恢复。

与具体阶段无关：上下游关系由项目流水线（`project_pipeline`）和各阶段的
`StageDefinition.reads()` 经 `upstream_of` 得出，一个阶段可以有多个上游。
`project_stages` 的状态：`locked` → `active` ⇄ `finalized`；全部上游都定稿后下游解锁；
任一上游重新定稿且内容变化时下游变为 `stale`（`stale_from` 记下原状态）；所有上游都对得上时
恢复：上游改回原样回到原状态（`finalized` 或 `active`），下游下一轮成功结束回到 `active`。
下游在 `based_on` 里按上游记录所基于的定稿快照；定稿和恢复时刷成各上游当前的定稿。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Engine

from studio.agent.stage import StageDefinition, StageRegistry, in_artifacts, upstream_of
from studio.db.repo.projects import get_project, set_current_stage
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


def project_pipeline(engine: Engine, project_id: str) -> list[str]:
    """项目的阶段流水线：`settings["pipeline"]`；老项目没有该字段时取阶段行的创建顺序。"""
    project = get_project(engine, project_id)
    pipeline = project.settings.get("pipeline") if project is not None else None
    if isinstance(pipeline, list):
        return [str(name) for name in pipeline]
    return [row.stage for row in list_stages(engine, project_id)]


def initial_statuses(pipeline: Sequence[str], registry: StageRegistry) -> list[tuple[str, str]]:
    """新项目各阶段的初始状态：流水线里没有上游的阶段 `active`，其余 `locked`。"""
    return [
        (name, "locked" if upstream_of(pipeline, registry, name) else "active") for name in pipeline
    ]


def _downstream_of(
    pipeline: Sequence[str],
    registry: StageRegistry,
    stages: list[StageValue],
    stage: str,
) -> list[StageValue]:
    return [row for row in stages if stage in upstream_of(pipeline, registry, row.stage)]


def _artifacts_of(manifest: Manifest, definition: StageDefinition) -> Manifest:
    """清单里属于该阶段产物（目录或文件条目）的那部分（快照是整项目的，判断内容变化只看产物目录）。"""
    entries = definition.artifact_dirs()
    return {path: sha for path, sha in manifest.items() if in_artifacts(entries, path)}


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


def current_stage_of(stages: list[StageValue]) -> str | None:
    """项目当前所处的阶段：第一个未定稿的阶段；全部定稿则是最后一个阶段。

    `stages` 按创建顺序（即流程顺序）排列；没有阶段行时返回 `None`。
    """
    if not stages:
        return None
    return next((s.stage for s in stages if s.status != "finalized"), stages[-1].stage)


def _sync_current_stage(engine: Engine, project_id: str) -> None:
    """把 `projects.current_stage` 对齐到阶段行的状态（定稿/重新打开之后调用）。"""
    stage = current_stage_of(list_stages(engine, project_id))
    if stage is not None:
        set_current_stage(engine, project_id, stage)


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
    pipeline = project_pipeline(engine, project_id)
    # Finalizing declares the stage consistent with its upstreams as they are now (TD-64).
    finalized = update_stage(
        engine,
        project_id,
        stage,
        status="finalized",
        finalized_snapshot_id=snapshot.id,
        finalized_at=datetime.now(UTC),
        based_on=_current_based_on(engine, registry, pipeline, project_id, current),
    )

    stages = list_stages(engine, project_id)
    for row in _downstream_of(pipeline, registry, stages, stage):
        if row.status == "locked":
            _unlock_if_ready(engine, registry, pipeline, project_id, row)
        else:
            _reconcile(engine, registry, pipeline, project_id, row)
    _sync_current_stage(engine, project_id)
    return finalized


def _unlock_if_ready(
    engine: Engine,
    registry: StageRegistry,
    pipeline: Sequence[str],
    project_id: str,
    row: StageValue,
) -> None:
    """`locked` 的下游：只有**全部**上游都已定稿才解锁，`based_on` 记下它们当前的定稿快照。"""
    based_on: dict[str, str] = {}
    for name in upstream_of(pipeline, registry, row.stage):
        upstream = get_stage(engine, project_id, name)
        if (
            upstream is None
            or upstream.status != "finalized"
            or upstream.finalized_snapshot_id is None
        ):
            return
        based_on[name] = upstream.finalized_snapshot_id
    update_stage(engine, project_id, row.stage, status="active", based_on=based_on)


def _current_based_on(
    engine: Engine,
    registry: StageRegistry,
    pipeline: Sequence[str],
    project_id: str,
    row: StageValue,
) -> dict[str, str]:
    """`row` 的 `based_on` 刷成各上游当前的定稿快照；从未定稿的上游保留原记录。"""
    based_on = dict(row.based_on)
    for name in upstream_of(pipeline, registry, row.stage):
        upstream = get_stage(engine, project_id, name)
        if upstream is not None and upstream.finalized_snapshot_id is not None:
            based_on[name] = upstream.finalized_snapshot_id
    return based_on


def _reconcile(
    engine: Engine,
    registry: StageRegistry,
    pipeline: Sequence[str],
    project_id: str,
    row: StageValue,
) -> None:
    """非 `locked` 的下游：逐个上游比较所基于的快照与上游当前定稿（只看上游产物目录）。

    任一上游有变化 → `stale`，`stale_from` 记下原状态；全部没有变化且原来是 `stale` →
    回到 `stale_from`（上游已经改回下游所基于的样子；已定稿的回到 `finalized`，TD-65），
    `based_on` 刷成各上游当前定稿；否则不动。上游从未定稿时没有可比较的版本，跳过它。
    """
    changed = False
    for name in upstream_of(pipeline, registry, row.stage):
        upstream = get_stage(engine, project_id, name)
        if upstream is None or upstream.finalized_snapshot_id is None:
            continue
        based_on_id = row.based_on.get(name)
        if based_on_id == upstream.finalized_snapshot_id:
            continue
        current = get_snapshot(engine, upstream.finalized_snapshot_id)
        if current is None or _upstream_artifacts_changed(
            engine, registry.get(name), based_on_id, current.manifest
        ):
            changed = True
            break
    if changed:
        if row.status != "stale":
            update_stage(engine, project_id, row.stage, status="stale", stale_from=row.status)
    elif row.status == "stale":
        update_stage(
            engine,
            project_id,
            row.stage,
            status="finalized" if row.stale_from == "finalized" else "active",
            based_on=_current_based_on(engine, registry, pipeline, project_id, row),
        )


def reopen(engine: Engine, project_id: str, stage: str) -> StageValue:
    """重新打开已定稿阶段：状态回到 `active`；下游在它重新定稿前仍读旧定稿版本。"""
    current = _require_stage(engine, project_id, stage)
    if current.status != "finalized":
        raise StageFlowError(f"阶段 {stage} 当前为 {current.status}，只有已定稿阶段能重新打开")
    reopened = update_stage(engine, project_id, stage, status="active")
    _sync_current_stage(engine, project_id)
    return reopened


def after_turn_done(
    engine: Engine, project_id: str, stage: str, used_upstream: dict[str, str | None]
) -> None:
    """下游一轮成功结束后，把 `based_on` 更新为**本轮开始时**物化的全部已定稿上游
    （`used_upstream`，来自 `upstream_snapshot_ids`；`None` 的跳过），而不是轮末的最新
    定稿——轮中上游又定稿了的话，agent 并没有看到新版本。只有每个用到的版本都仍是
    该上游当前定稿时，`stale` 才回到 `active`。
    """
    current = get_stage(engine, project_id, stage)
    used = {name: sid for name, sid in used_upstream.items() if sid is not None}
    if current is None or not used:
        return
    up_to_date = True
    for name, snapshot_id in used.items():
        upstream = get_stage(engine, project_id, name)
        if upstream is None or upstream.finalized_snapshot_id != snapshot_id:
            up_to_date = False
            break
    status = "active" if current.status == "stale" and up_to_date else None
    if used == current.based_on and status is None:
        return
    update_stage(engine, project_id, stage, status=status, based_on=used)


def upstream_snapshot_ids(
    engine: Engine, registry: StageRegistry, project_id: str, stage_name: str
) -> dict[str, str | None]:
    """流水线里每个上游阶段当前的 `finalized_snapshot_id`（未定稿为 `None`）。"""
    ids: dict[str, str | None] = {}
    for name in upstream_of(project_pipeline(engine, project_id), registry, stage_name):
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
    engine: Engine, registry: StageRegistry, project_id: str, stage_name: str
) -> dict[str, Manifest | None]:
    """流水线里每个上游阶段的定稿快照清单（未定稿为 `None`）。"""
    return manifests_of(engine, upstream_snapshot_ids(engine, registry, project_id, stage_name))
