"""上下文前言（设计 §4.4 第 4 步）：每轮放在用户消息之前的工作区状态说明。

分两部分：

- `build_preamble(inputs)`：纯函数，把 `PreambleInputs` 渲染成文本；没有任何
  内容时返回空串。
- `gather_preamble_inputs(...)`：从数据库和工作区收集这些信息。跨轮需要的
  状态全部来自持久化数据，进程重启后仍然成立：
  - 上一轮被还原的路径：上一轮结束时写入的 `notice` 事件
    （`payload.kind == "guard_restored"`）；
  - 回滚通知：上一轮结束之后项目里出现的 `reason=rollback` 快照；回滚目标是
    它之前清单完全相同的最近一份快照（回滚会原样写回目标清单）；
  - 上游新定稿：本阶段 `based_on_snapshot_id` 与上游当前 `finalized_snapshot_id`
    不同时，两份清单在上游产物目录下的文件级差异；叙事→动画这一条边额外按镜头
    id 给出新增/删除/旁白变化/beat 变化摘要（设计 §5.4，TD-6），渲染时优先用它；
  - 用户手动修改：本会话上一轮结束（`turns.updated_at`）之后、到本轮开始快照
    为止，项目里每一份 `reason=user_edit` 快照（本轮开始时、其他阶段的 turn
    开始时、定稿时创建的）相对各自前一份快照的 diff，按路径合并（基准取最早
    一次改动前的内容，结果取最后一次）。这样用户的修改即使先被别的快照吸收，
    也不会从本会话的前言里消失；新会话只看本轮自己的 `user_edit` 快照。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from studio.agent.stage import StageDefinition
from studio.db.repo.snapshots import get_snapshot, list_snapshots
from studio.db.repo.stages import get_stage
from studio.db.repo.turns import TurnValue, list_turn_events
from studio.workspace import BlobStore, Manifest, WorkspaceDiff, diff, list_tree

DIFF_MAX_CHARS_PER_FILE = 1500
DIFF_MAX_CHARS_TOTAL = 6000

GUARD_RESTORED_NOTICE = "guard_restored"


@dataclass(frozen=True, slots=True)
class UpstreamChange:
    stage: str
    diff: WorkspaceDiff
    scene_summary: list[str] | None = None
    """按镜头 id 的变更摘要（每项一行）；只有叙事→动画这条边会填，且解析失败
    时为 `None`（渲染退回文件级摘要）。空列表表示镜头内容没有变化。"""


@dataclass(frozen=True, slots=True)
class RollbackNotice:
    rollback_snapshot_id: str
    target_snapshot_id: str | None
    diff: WorkspaceDiff | None
    """相对 agent 上一轮结束时的工作区（上一轮的 `end_snapshot`）。"""


@dataclass(frozen=True, slots=True)
class PreambleInputs:
    user_edits: WorkspaceDiff | None = None
    upstream_changes: list[UpstreamChange] = field(default_factory=list)
    restored_paths: list[str] = field(default_factory=list)
    rollback: RollbackNotice | None = None
    status_summary: str = ""
    handoff_files: list[str] = field(default_factory=list)


def _is_empty(value: WorkspaceDiff | None) -> bool:
    return value is None or not (value.added or value.removed or value.modified)


def _file_summary(value: WorkspaceDiff) -> list[str]:
    lines = [f"- 新增 {path}" for path in value.added]
    lines += [f"- 删除 {path}" for path in value.removed]
    lines += [f"- 修改 {item.path}" for item in value.modified]
    return lines


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（diff 已截断）"


def _user_edits_section(value: WorkspaceDiff) -> list[str]:
    lines = [
        "## 用户手动修改的文件",
        "自上一轮以来，用户手动修改了这些文件：",
        *_file_summary(value),
    ]
    budget = DIFF_MAX_CHARS_TOTAL
    for item in value.modified:
        if item.text_diff is None:
            continue
        if budget <= 0:
            lines.append("（其余 diff 已省略）")
            break
        snippet = _truncate(item.text_diff, min(DIFF_MAX_CHARS_PER_FILE, budget))
        budget -= len(snippet)
        lines += ["```diff", snippet.rstrip("\n"), "```"]
    return lines


def build_preamble(inputs: PreambleInputs) -> str:
    """把收集到的信息渲染成前言文本；没有任何内容时返回空串。"""
    sections: list[list[str]] = []

    if inputs.user_edits is not None and not _is_empty(inputs.user_edits):
        sections.append(_user_edits_section(inputs.user_edits))

    upstream = [change for change in inputs.upstream_changes if not _is_empty(change.diff)]
    if upstream:
        lines = ["## 上游新定稿"]
        for change in upstream:
            lines.append(
                f"上游阶段 {change.stage} 重新定稿了，只读副本 upstream/{change.stage}/ 已更新："
            )
            if change.scene_summary is None:
                lines += _file_summary(change.diff)
            elif change.scene_summary:
                lines += change.scene_summary
            else:
                lines.append("- 镜头没有变化（只有配音时间轴等其它文件有变化）")
        sections.append(lines)

    if inputs.restored_paths:
        sections.append(
            [
                "## 上一轮被还原的越界改动",
                "以下路径不在本阶段可写范围内，上一轮对它们的改动已被还原：",
                *[f"- {path}" for path in inputs.restored_paths],
            ]
        )

    if inputs.rollback is not None:
        notice = inputs.rollback
        target = notice.target_snapshot_id or notice.rollback_snapshot_id
        lines = ["## 回滚通知", f"用户已把工作区回滚到快照 {target}。"]
        if notice.diff is not None and not _is_empty(notice.diff):
            lines.append("与你上一轮结束时相比：")
            lines += _file_summary(notice.diff)
        sections.append(lines)

    if inputs.status_summary:
        sections.append(["## 当前产物状态", inputs.status_summary])

    if inputs.handoff_files:
        sections.append(
            [
                "## 会话交接",
                "这是一个新会话，之前的工作都在工作区文件里。本阶段现有产物：",
                *[f"- {path}" for path in inputs.handoff_files],
            ]
        )

    if not sections:
        return ""
    header = "[上下文前言：以下内容由系统自动生成，描述工作区的最新状态，不是用户的话]"
    return "\n\n".join([header, *("\n".join(section) for section in sections)])


def compose_user_text(preamble: str, user_text: str) -> str:
    """前言放在用户消息之前；前言为空时原样返回用户消息。"""
    if not preamble:
        return user_text
    return f"{preamble}\n\n---\n\n{user_text}"


def _restored_paths(engine: Engine, previous: TurnValue | None) -> list[str]:
    if previous is None:
        return []
    paths: list[str] = []
    for event in list_turn_events(engine, previous.id):
        if event.type == "notice" and event.payload.get("kind") == GUARD_RESTORED_NOTICE:
            paths += [str(path) for path in event.payload.get("paths", [])]
    return paths


def _rollback_notice(
    engine: Engine, blobs: BlobStore, project_id: str, previous: TurnValue | None
) -> RollbackNotice | None:
    if previous is None:
        return None
    snapshots = list_snapshots(engine, project_id)
    rollbacks = [
        (index, snap)
        for index, snap in enumerate(snapshots)
        if snap.reason == "rollback" and snap.created_at > previous.updated_at
    ]
    if not rollbacks:
        return None
    index, rollback = rollbacks[-1]
    target = next(
        (snap for snap in reversed(snapshots[:index]) if snap.manifest == rollback.manifest),
        None,
    )
    end = get_snapshot(engine, previous.end_snapshot_id) if previous.end_snapshot_id else None
    return RollbackNotice(
        rollback_snapshot_id=rollback.id,
        target_snapshot_id=target.id if target is not None else None,
        diff=diff(end.manifest, rollback.manifest, blobs) if end is not None else None,
    )


_NARRATIVE_PATH = "narrative/narrative.json"


def _read_scenes(manifest: Manifest, blobs: BlobStore) -> dict[str, dict[str, Any]]:
    """按 id 索引 `narrative.json` 的镜头；缺文件、JSON 非法、缺 `id` 都会抛异常。"""
    document = json.loads(blobs.get(manifest[_NARRATIVE_PATH]).decode("utf-8"))
    scenes: dict[str, dict[str, Any]] = {}
    for scene in document["scenes"]:
        scenes[scene["id"]] = scene
    return scenes


def _narrative_scene_summary(
    old_manifest: Manifest, new_manifest: Manifest, blobs: BlobStore
) -> list[str] | None:
    """叙事→动画边的按镜头 id 摘要；任何一步解析失败返回 `None`，调用方退回
    文件级 diff（不能因为一份 JSON 坏了让整轮前言生成失败）。
    """
    try:
        old = _read_scenes(old_manifest, blobs)
        new = _read_scenes(new_manifest, blobs)
    except (KeyError, TypeError, ValueError, OSError):
        return None
    lines = [f"- 新增镜头 {sid}" for sid in new if sid not in old]
    lines += [f"- 删除镜头 {sid}" for sid in old if sid not in new]
    for sid, scene in new.items():
        before = old.get(sid)
        if before is None:
            continue
        if before.get("narration") != scene.get("narration"):
            lines.append(f"- 镜头 {sid} 旁白有改动")
        elif before.get("beats") != scene.get("beats"):
            lines.append(f"- 镜头 {sid} 的 beat 拆分有改动")
    return lines


def _upstream_changes(
    engine: Engine, blobs: BlobStore, project_id: str, stage: StageDefinition
) -> list[UpstreamChange]:
    current = get_stage(engine, project_id, stage.name)
    if current is None or current.based_on_snapshot_id is None:
        return []
    based_on = get_snapshot(engine, current.based_on_snapshot_id)
    if based_on is None:
        return []
    changes: list[UpstreamChange] = []
    for name in stage.reads():
        row = get_stage(engine, project_id, name)
        if row is None or row.finalized_snapshot_id in (None, current.based_on_snapshot_id):
            continue
        finalized = get_snapshot(engine, row.finalized_snapshot_id or "")
        if finalized is None:
            continue
        prefix = f"{name}/"
        old = {p: h for p, h in based_on.manifest.items() if p.startswith(prefix)}
        new = {p: h for p, h in finalized.manifest.items() if p.startswith(prefix)}
        scene_summary = _narrative_scene_summary(old, new, blobs) if name == "narrative" else None
        changes.append(
            UpstreamChange(stage=name, diff=diff(old, new, blobs), scene_summary=scene_summary)
        )
    return changes


def _user_edits(
    engine: Engine,
    blobs: BlobStore,
    project_id: str,
    previous: TurnValue | None,
    start_snapshot_id: str,
) -> WorkspaceDiff | None:
    snapshots = list_snapshots(engine, project_id)
    ids = [snap.id for snap in snapshots]
    if start_snapshot_id not in ids:
        return None
    before: dict[str, str | None] = {}
    after: dict[str, str | None] = {}
    for index in range(1, ids.index(start_snapshot_id) + 1):
        snap = snapshots[index]
        if snap.reason != "user_edit":
            continue
        if previous is None and snap.id != start_snapshot_id:
            continue
        if previous is not None and snap.created_at <= previous.updated_at:
            continue
        predecessor = snapshots[index - 1].manifest
        for path in set(predecessor) | set(snap.manifest):
            if predecessor.get(path) == snap.manifest.get(path):
                continue
            before.setdefault(path, predecessor.get(path))
            after[path] = snap.manifest.get(path)
    old = {path: sha for path, sha in before.items() if sha is not None}
    new = {path: sha for path, sha in after.items() if sha is not None}
    return diff(old, new, blobs)


def _handoff_files(workdir: Path, stage: StageDefinition) -> list[str]:
    prefixes = tuple(f"{name}/" for name in stage.artifact_dirs())
    return [path for path in list_tree(workdir) if path.startswith(prefixes)]


def gather_preamble_inputs(
    engine: Engine,
    blobs: BlobStore,
    *,
    workdir: Path,
    project_id: str,
    stage: StageDefinition,
    previous: TurnValue | None,
    start_snapshot_id: str,
) -> PreambleInputs:
    """收集本轮前言需要的信息；`previous` 是本会话上一轮（新会话为 `None`），
    `start_snapshot_id` 是本轮开始时的快照。
    """
    return PreambleInputs(
        user_edits=_user_edits(engine, blobs, project_id, previous, start_snapshot_id),
        upstream_changes=_upstream_changes(engine, blobs, project_id, stage),
        restored_paths=_restored_paths(engine, previous),
        rollback=_rollback_notice(engine, blobs, project_id, previous),
        status_summary=stage.status_summary(workdir),
        handoff_files=_handoff_files(workdir, stage) if previous is None else [],
    )
