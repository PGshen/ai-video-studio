"""`suggestions` 仓储：跨阶段的回退建议（设计 §5.4；ARCHITECTURE 规则 5）。

`status` 取值：`open`（初始）、`applied`、`dismissed`——后两个由 M5 的 UI
真正触发，本模块只保证 `update_suggestion_status` 存在且行为正确。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select

from studio.db.engine import session_scope
from studio.db.models import Suggestion


@dataclass(frozen=True, slots=True)
class SuggestionValue:
    """`suggestions` 表一行的只读值对象。"""

    id: str
    project_id: str
    from_stage: str
    to_stage: str
    content: str
    status: str
    turn_id: str | None
    created_at: datetime


def _to_value(row: Suggestion) -> SuggestionValue:
    return SuggestionValue(
        id=row.id,
        project_id=row.project_id,
        from_stage=row.from_stage,
        to_stage=row.to_stage,
        content=row.content,
        status=row.status,
        turn_id=row.turn_id,
        created_at=row.created_at,
    )


def create_suggestion(
    engine: Engine,
    *,
    project_id: str,
    from_stage: str,
    to_stage: str,
    content: str,
    turn_id: str | None = None,
) -> SuggestionValue:
    """插入一条 `status="open"` 的回退建议。"""
    with session_scope(engine) as db:
        row = Suggestion(
            project_id=project_id,
            from_stage=from_stage,
            to_stage=to_stage,
            content=content,
            turn_id=turn_id,
            status="open",
        )
        db.add(row)
        db.flush()
        return _to_value(row)


def get_suggestion(engine: Engine, suggestion_id: str) -> SuggestionValue | None:
    """按 id 查询建议，不存在时返回 `None`。"""
    with session_scope(engine) as db:
        row = db.get(Suggestion, suggestion_id)
        return _to_value(row) if row is not None else None


def list_suggestions(
    engine: Engine, project_id: str, status: str | None = None
) -> list[SuggestionValue]:
    """项目的全部建议，按创建时间升序；`status` 传了就过滤。"""
    with session_scope(engine) as db:
        stmt = select(Suggestion).where(Suggestion.project_id == project_id)
        if status is not None:
            stmt = stmt.where(Suggestion.status == status)
        stmt = stmt.order_by(Suggestion.created_at.asc())
        rows = db.scalars(stmt).all()
        return [_to_value(row) for row in rows]


def update_suggestion_status(engine: Engine, suggestion_id: str, status: str) -> SuggestionValue:
    """把建议标记为 `applied`/`dismissed`（M5 才会真正调用）。"""
    with session_scope(engine) as db:
        row = db.get(Suggestion, suggestion_id)
        if row is None:
            raise KeyError(suggestion_id)
        row.status = status
        db.flush()
        return _to_value(row)
