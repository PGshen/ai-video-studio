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
