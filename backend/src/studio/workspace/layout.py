"""工作区目录布局（设计 §3.3）。

项目工作区固定为 `<data_dir>/projects/<project_id>/`，其中几个顶层目录不参与
快照：`.cache/`（临时产物）、`output/`（成片渲染结果）、`upstream/`（TurnRunner
每轮刷新的上游只读副本，T4 实现）。
"""

from __future__ import annotations

import os
from pathlib import Path

EXCLUDED_TOP_DIRS = {".cache", "output", "upstream"}

HIDDEN_TOP_DIRS = EXCLUDED_TOP_DIRS - {"upstream"}
"""对 agent/前端只读接口隐藏的顶层目录：`upstream/` 仍然可见（只读展示上游
产物），`.cache/`、`output/` 不是"工作区内容"，不应该被 `list_tree`/`read_text`
或 `/api/projects/{id}/files` 列出或读到（TD-5）。"""


def project_dir(data_dir: Path | str, project_id: str) -> Path:
    """返回项目工作区目录（不保证已存在）。"""
    return Path(data_dir) / "projects" / project_id


def scratch_dir(data_dir: Path | str, session_id: str) -> Path:
    """无项目会话（头脑风暴）的 scratch 目录 `<data_dir>/scratch/<session_id>/`（不保证已存在）。

    它只是原生文件工具/Shell 需要的一个 cwd：不快照、不参与任何项目，每轮开始前清空。
    """
    return Path(data_dir) / "scratch" / session_id


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


def prune_empty_dirs(workdir: Path) -> None:
    """删除工作区里因为文件被移走/还原而产生的空目录，不动排除目录。

    供 `snapshot.rollback` 和 `scope.guard` 共用：两者都会删除或改写文件，
    删空的目录如果不清理会一直留在工作区里（TD-5）。
    """
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
