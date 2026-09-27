"""工作区模块：布局、快照库、diff、回滚（设计 §3.3）。

唯一读写工作区文件的模块（ARCHITECTURE §2 规则 6）；agent 的原生文件工具
除外，它们受越界检查约束（T4）。
"""

from __future__ import annotations

from studio.workspace.blobs import BlobStore
from studio.workspace.layout import EXCLUDED_TOP_DIRS, project_dir
from studio.workspace.snapshot import (
    Manifest,
    ModifiedFile,
    SnapshotRef,
    WorkspaceDiff,
    create_snapshot,
    diff,
    read_file_at,
    rollback,
    scan,
)

__all__ = [
    "BlobStore",
    "EXCLUDED_TOP_DIRS",
    "Manifest",
    "ModifiedFile",
    "SnapshotRef",
    "WorkspaceDiff",
    "create_snapshot",
    "diff",
    "project_dir",
    "read_file_at",
    "rollback",
    "scan",
]
