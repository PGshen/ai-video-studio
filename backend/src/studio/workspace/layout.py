"""工作区目录布局（设计 §3.3）。

项目工作区固定为 `<data_dir>/projects/<project_id>/`，其中几个顶层目录不参与
快照：`.cache/`（临时产物）、`output/`（成片渲染结果）、`upstream/`（TurnRunner
每轮刷新的上游只读副本，T4 实现）。
"""

from __future__ import annotations

from pathlib import Path

EXCLUDED_TOP_DIRS = {".cache", "output", "upstream"}


def project_dir(data_dir: Path | str, project_id: str) -> Path:
    """返回项目工作区目录（不保证已存在）。"""
    return Path(data_dir) / "projects" / project_id


class PathEscapesWorkdir(Exception):
    """相对路径解析后落在工作区之外。"""


def resolve_relpath(workdir: Path | str, relpath: str) -> Path:
    """解析 `relpath` 相对 `workdir` 的路径；解析后越出工作区时抛出 `PathEscapesWorkdir`。

    供 `snapshot._safe_dest`、`files.safe_path` 共用的路径包含性检查：用
    `Path.resolve()` 归一化（含符号链接、`..`），再确认结果仍在 `workdir` 内。
    """
    workdir = Path(workdir)
    dest = (workdir / relpath).resolve()
    workdir_resolved = workdir.resolve()
    if dest != workdir_resolved and workdir_resolved not in dest.parents:
        raise PathEscapesWorkdir(relpath)
    return workdir / relpath
