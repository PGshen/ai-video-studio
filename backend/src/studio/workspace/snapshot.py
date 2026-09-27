"""快照库（设计 §3.3）：扫描、创建快照、对比、回滚、读历史版本。

不使用 git：agent 开放了 Shell，工作区里如果有 `.git` 会被 agent 自行执行的
`git` 命令破坏。快照元数据存在 `snapshots` 表里，内容存在 `BlobStore` 中，都
在工作区之外，agent 看不到也改不了。
"""

from __future__ import annotations

import difflib
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine

from studio.db.repo.snapshots import (
    SnapshotValue,
    get_snapshot,
    insert_snapshot,
    latest_snapshot,
)
from studio.workspace.blobs import BlobStore
from studio.workspace.layout import (
    EXCLUDED_TOP_DIRS,
    PathEscapesWorkdir,
    project_dir,
    resolve_relpath,
)

# 相对路径（POSIX 风格）→ sha256 十六进制摘要。
Manifest = dict[str, str]


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    """一份快照的只读引用。"""

    id: str
    project_id: str
    manifest: Manifest
    reason: str
    turn_id: str | None
    created_at: datetime
    created: bool
    """本次调用是否新建了快照；清单与最近一份相同时为 `False`。"""


@dataclass(frozen=True, slots=True)
class ModifiedFile:
    """一个被修改文件的对比结果。"""

    path: str
    old_sha256: str
    new_sha256: str
    text_diff: str | None
    """unified diff 文本；两侧任一内容不是合法 UTF-8 文本时为 `None`。"""


@dataclass(frozen=True, slots=True)
class WorkspaceDiff:
    """两份清单的差异。"""

    added: list[str]
    removed: list[str]
    modified: list[ModifiedFile]


def _to_ref(value: SnapshotValue, *, created: bool) -> SnapshotRef:
    return SnapshotRef(
        id=value.id,
        project_id=value.project_id,
        manifest=value.manifest,
        reason=value.reason,
        turn_id=value.turn_id,
        created_at=value.created_at,
        created=created,
    )


def _data_dir_of(blobs: BlobStore) -> Path:
    """从 blob 根目录反推 `data_dir`（约定：`<data_dir>/blobs/`）。"""
    if blobs.root.name != "blobs":
        raise ValueError(f"BlobStore.root 必须命名为 'blobs'，实际是：{blobs.root}")
    return blobs.root.parent


def scan(workdir: Path | str) -> Manifest:
    """扫描工作区，返回 `{POSIX 相对路径: sha256}`。

    只收录普通文件：跳过符号链接（文件或目录）、跳过顶层的排除目录
    （`EXCLUDED_TOP_DIRS`）。目录不存在时返回空清单。
    """
    workdir = Path(workdir)
    manifest: Manifest = {}
    if not workdir.is_dir():
        return manifest

    for root, dirnames, filenames in os.walk(workdir, followlinks=False):
        root_path = Path(root)
        if root_path == workdir:
            dirnames[:] = [name for name in dirnames if name not in EXCLUDED_TOP_DIRS]

        for filename in filenames:
            file_path = root_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            rel_path = file_path.relative_to(workdir).as_posix()
            manifest[rel_path] = _sha256_of(file_path.read_bytes())

    return manifest


def _sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_snapshot(
    engine: Engine,
    blobs: BlobStore,
    project_id: str,
    reason: str,
    turn_id: str | None = None,
) -> SnapshotRef:
    """扫描工作区并创建快照；清单与最近一份相同时返回已有快照，`created=False`。"""
    workdir = project_dir(_data_dir_of(blobs), project_id)
    manifest = scan(workdir)

    latest = latest_snapshot(engine, project_id)
    if latest is not None and latest.manifest == manifest:
        return _to_ref(latest, created=False)

    for rel_path in manifest:
        blobs.put((workdir / rel_path).read_bytes())

    value = insert_snapshot(
        engine, project_id=project_id, manifest=manifest, reason=reason, turn_id=turn_id
    )
    return _to_ref(value, created=True)


def _try_text(blobs: BlobStore, sha256: str) -> str | None:
    try:
        return blobs.get(sha256).decode("utf-8")
    except UnicodeDecodeError:
        return None


def diff(old: Manifest, new: Manifest, blobs: BlobStore) -> WorkspaceDiff:
    """对比两份清单：新增、删除、修改；修改的文本文件附 unified diff。"""
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))

    modified: list[ModifiedFile] = []
    for path in sorted(set(old) & set(new)):
        old_sha256, new_sha256 = old[path], new[path]
        if old_sha256 == new_sha256:
            continue

        old_text = _try_text(blobs, old_sha256)
        new_text = _try_text(blobs, new_sha256)
        text_diff: str | None = None
        if old_text is not None and new_text is not None:
            text_diff = "".join(
                difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
        modified.append(
            ModifiedFile(
                path=path, old_sha256=old_sha256, new_sha256=new_sha256, text_diff=text_diff
            )
        )

    return WorkspaceDiff(added=added, removed=removed, modified=modified)


def read_file_at(blobs: BlobStore, manifest: Manifest, path: str) -> bytes:
    """按某份清单读取一个文件的历史内容。"""
    sha256 = manifest.get(path)
    if sha256 is None:
        raise FileNotFoundError(path)
    return blobs.get(sha256)


def _safe_dest(workdir: Path, rel_path: str) -> Path:
    """校验清单路径落在工作区内，返回目标绝对路径。"""
    try:
        return resolve_relpath(workdir, rel_path)
    except PathEscapesWorkdir as exc:
        raise ValueError(f"清单路径越出工作区：{rel_path}") from exc


def _prune_empty_dirs(workdir: Path) -> None:
    """删除回滚后产生的空目录，不动排除目录。"""
    for dirpath, _dirnames, _filenames in os.walk(workdir, topdown=False):
        path = Path(dirpath)
        if path == workdir:
            continue
        rel_parts = path.relative_to(workdir).parts
        if rel_parts and rel_parts[0] in EXCLUDED_TOP_DIRS:
            continue
        try:
            next(path.iterdir())
        except StopIteration:
            path.rmdir()
        except FileNotFoundError:
            pass


def rollback(
    engine: Engine,
    blobs: BlobStore,
    project_id: str,
    target_snapshot_id: str,
) -> SnapshotRef:
    """回滚到目标快照：写回清单内容、删除清单外文件，再新建 `reason=rollback` 快照。

    覆盖之前先给当前工作区拍一份 `reason=user_edit` 快照（内容未变时不新建，
    与 `stage_flow.finalize` 一致）：用户通过文件接口做的手动修改不会自动
    快照，不先拍的话回滚会把它们永久覆盖，回滚本身也无法撤销。

    排除目录（`EXCLUDED_TOP_DIRS`）不参与快照，回滚不会触碰它们。
    """
    target = get_snapshot(engine, target_snapshot_id)
    if target is None:
        raise ValueError(f"快照不存在：{target_snapshot_id}")
    if target.project_id != project_id:
        raise ValueError(f"快照不属于项目 {project_id}：{target_snapshot_id}")

    create_snapshot(engine, blobs, project_id, reason="user_edit")

    workdir = project_dir(_data_dir_of(blobs), project_id)
    workdir.mkdir(parents=True, exist_ok=True)

    for rel_path, sha256 in target.manifest.items():
        dest = _safe_dest(workdir, rel_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blobs.get(sha256))

    current = scan(workdir)
    for rel_path in current:
        if rel_path not in target.manifest:
            _safe_dest(workdir, rel_path).unlink()

    _prune_empty_dirs(workdir)

    return create_snapshot(engine, blobs, project_id, reason="rollback")
