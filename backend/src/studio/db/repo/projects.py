"""`projects` 仓储：创建与查询（设计 §3.1）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine

from studio.db.engine import session_scope
from studio.db.models import Project


@dataclass(frozen=True, slots=True)
class ProjectValue:
    """`projects` 表一行的只读值对象。"""

    id: str
    title: str
    idea_id: str | None
    current_stage: str
    settings: dict[str, Any]


def _to_value(row: Project) -> ProjectValue:
    return ProjectValue(
        id=row.id,
        title=row.title,
        idea_id=row.idea_id,
        current_stage=row.current_stage,
        settings=row.settings,
    )


def create_project(
    engine: Engine,
    *,
    title: str,
    idea_id: str | None = None,
    settings: dict[str, Any] | None = None,
) -> ProjectValue:
    """创建一个项目，`current_stage` 使用表定义的默认值（`topic`）。"""
    with session_scope(engine) as session:
        project = Project(title=title, idea_id=idea_id, settings=settings or {})
        session.add(project)
        session.flush()
        return _to_value(project)


def get_project(engine: Engine, project_id: str) -> ProjectValue | None:
    """按 id 查询项目，不存在时返回 `None`。"""
    with session_scope(engine) as session:
        row = session.get(Project, project_id)
        return _to_value(row) if row is not None else None
