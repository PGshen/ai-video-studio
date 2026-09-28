"""`projects` 仓储：创建与查询（设计 §3.1）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, select

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
    id: str | None = None,
    title: str,
    idea_id: str | None = None,
    settings: dict[str, Any] | None = None,
) -> ProjectValue:
    """创建一个项目，`current_stage` 使用表定义的默认值（`topic`）。

    `id` 一般留空，由表定义的默认值（`uuid4().hex`）生成；T7 的项目创建流程
    需要先知道 project id 才能初始化工作区目录（`style/STYLE.md`、`init`
    快照），再插入这一行，所以显式传入。
    """
    with session_scope(engine) as session:
        project = Project(title=title, idea_id=idea_id, settings=settings or {})
        if id is not None:
            project.id = id
        session.add(project)
        session.flush()
        return _to_value(project)


def get_project(engine: Engine, project_id: str) -> ProjectValue | None:
    """按 id 查询项目，不存在时返回 `None`。"""
    with session_scope(engine) as session:
        row = session.get(Project, project_id)
        return _to_value(row) if row is not None else None


def list_projects(engine: Engine) -> list[ProjectValue]:
    """全部项目，按创建时间倒序（最近创建的在前）。"""
    with session_scope(engine) as session:
        rows = session.scalars(select(Project).order_by(Project.created_at.desc())).all()
        return [_to_value(row) for row in rows]


def delete_project(engine: Engine, project_id: str) -> None:
    """删除一个项目行；不存在时是空操作（项目创建失败时的清理用，见 `api.projects`）。"""
    with session_scope(engine) as session:
        row = session.get(Project, project_id)
        if row is not None:
            session.delete(row)
