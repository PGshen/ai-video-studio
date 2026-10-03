"""`projects` 仓储：创建与查询（设计 §3.1）。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import Engine, select

from studio.db.engine import session_scope
from studio.db.models import Project

ProjectStatus = Literal["active", "completed", "abandoned"]
PROJECT_STATUSES: tuple[ProjectStatus, ...] = ("active", "completed", "abandoned")


@dataclass(frozen=True, slots=True)
class ProjectValue:
    """`projects` 表一行的只读值对象。"""

    id: str
    title: str
    idea_id: str | None
    current_stage: str
    settings: dict[str, Any]
    completed_at: datetime | None
    abandoned_at: datetime | None

    @property
    def status(self) -> ProjectStatus:
        """由两个时间戳推导：`abandoned_at` → 已废弃，`completed_at` → 已完成，否则进行中。"""
        if self.abandoned_at is not None:
            return "abandoned"
        return "completed" if self.completed_at is not None else "active"


def _to_value(row: Project) -> ProjectValue:
    return ProjectValue(
        id=row.id,
        title=row.title,
        idea_id=row.idea_id,
        current_stage=row.current_stage,
        settings=row.settings,
        completed_at=row.completed_at,
        abandoned_at=row.abandoned_at,
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


def update_project_settings(
    engine: Engine, project_id: str, patch: Mapping[str, Any]
) -> ProjectValue:
    """把补丁合并进 `projects.settings`；值为 `None` 的键被移除。项目不存在抛 `LookupError`。

    JSON 列里的 dict 是可变对象，就地改不会被 SQLAlchemy 发现，所以整体替换成新 dict。
    哪些键允许改由调用方决定（M5 T8：API 只放行 `voice`/`speech_rate`）。
    """
    with session_scope(engine) as session:
        row = session.get(Project, project_id)
        if row is None:
            raise LookupError(project_id)
        merged = {**(row.settings or {}), **patch}
        row.settings = {key: value for key, value in merged.items() if value is not None}
        session.flush()
        return _to_value(row)


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


def mark_project_completed(engine: Engine, project_id: str) -> ProjectValue:
    """把项目标记为已完成：`completed_at` 设为当前时间（UTC）。

    项目不存在时抛出 `KeyError`（调用方——`api.animation`——在此之前已经用
    `get_project` 确认过项目存在，这里的检查是防御性的，不是主要的错误路径）。
    """
    with session_scope(engine) as session:
        row = session.get(Project, project_id)
        if row is None:
            raise KeyError(f"项目不存在：{project_id}")
        row.completed_at = datetime.now(UTC)
        row.abandoned_at = None
        session.flush()
        return _to_value(row)


def clear_project_completed(engine: Engine, project_id: str) -> ProjectValue:
    """把项目的"已完成"标记清掉：`completed_at` 设为 `None`。

    `mark_project_completed` 的反操作——重新打开动画阶段（评审发现，见计划
    决策记录）后，成片和当前工作区不再对得上，不能继续显示"项目已完成"。
    项目不存在时抛出 `KeyError`（同 `mark_project_completed`，防御性检查）。
    """
    with session_scope(engine) as session:
        row = session.get(Project, project_id)
        if row is None:
            raise KeyError(f"项目不存在：{project_id}")
        row.completed_at = None
        session.flush()
        return _to_value(row)


def set_project_status(engine: Engine, project_id: str, status: ProjectStatus) -> ProjectValue:
    """手动设置项目状态；三种状态互斥，切换时清掉另外两个时间戳。

    `active` 把两个标记都清掉；`completed`/`abandoned` 写入当前时间。项目不存在抛 `KeyError`。
    """
    with session_scope(engine) as session:
        row = session.get(Project, project_id)
        if row is None:
            raise KeyError(f"项目不存在：{project_id}")
        now = datetime.now(UTC)
        row.completed_at = now if status == "completed" else None
        row.abandoned_at = now if status == "abandoned" else None
        session.flush()
        return _to_value(row)


def set_current_stage(engine: Engine, project_id: str, stage: str) -> ProjectValue:
    """更新 `current_stage`（`stage_flow` 在定稿/重新打开后同步）。项目不存在抛 `KeyError`。"""
    with session_scope(engine) as session:
        row = session.get(Project, project_id)
        if row is None:
            raise KeyError(f"项目不存在：{project_id}")
        row.current_stage = stage
        session.flush()
        return _to_value(row)
