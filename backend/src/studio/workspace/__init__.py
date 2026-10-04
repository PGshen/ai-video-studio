"""工作区模块：布局、快照库、diff、回滚（设计 §3.3）。

唯一读写工作区文件的模块（ARCHITECTURE §2 规则 6）；agent 的原生文件工具
除外，它们受越界检查约束（T4）。
"""

from __future__ import annotations

from studio.workspace.blobs import BlobStore
from studio.workspace.files import (
    ScopeError,
    init_workspace,
    list_tree,
    read_bytes,
    read_text,
    remove_scratch,
    remove_workspace,
    reset_scratch,
    safe_path,
    write_text,
    write_text_unscoped,
)
from studio.workspace.layout import EXCLUDED_TOP_DIRS, project_dir, scratch_dir
from studio.workspace.scope import GuardReport, WriteScope, guard, is_writable
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
from studio.workspace.upstream import derived_upstream, materialize_upstream, upstream_drift

__all__ = [
    "BlobStore",
    "EXCLUDED_TOP_DIRS",
    "GuardReport",
    "Manifest",
    "ModifiedFile",
    "ScopeError",
    "SnapshotRef",
    "WorkspaceDiff",
    "WriteScope",
    "create_snapshot",
    "diff",
    "guard",
    "init_workspace",
    "is_writable",
    "list_tree",
    "derived_upstream",
    "materialize_upstream",
    "project_dir",
    "read_bytes",
    "read_file_at",
    "read_text",
    "remove_scratch",
    "remove_workspace",
    "reset_scratch",
    "rollback",
    "safe_path",
    "scratch_dir",
    "scan",
    "upstream_drift",
    "write_text",
    "write_text_unscoped",
]
