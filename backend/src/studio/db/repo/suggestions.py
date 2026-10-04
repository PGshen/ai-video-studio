"""`suggestions` 仓储：跨阶段的回退建议（设计 §5.4；ARCHITECTURE 规则 5）。

`status` 取值：`open`（初始）、`applied`、`dismissed`；状态机只有 `open → applied | dismissed`，
由 `resolve_suggestion` 执行（M5 T9，API `POST /suggestions/{id}/apply|dismiss`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, delete, func, select

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


class SuggestionStateError(RuntimeError):
    """建议已经处理过（`applied`/`dismissed`），不能再转移（API 映射为 409）。"""


def resolve_suggestion(engine: Engine, suggestion_id: str, status: str) -> SuggestionValue:
    """把 `open` 的建议转成 `applied` 或 `dismissed`（M5 T9）。

    状态机只有 `open → applied | dismissed`：已经处理过的再处理抛 `SuggestionStateError`，
    不改任何东西；`status` 不是这两个值抛 `ValueError`；建议不存在抛 `KeyError`。
    条件更新在同一个事务里完成，两个并发的处理请求只有一个会成功。
    """
    if status not in ("applied", "dismissed"):
        raise ValueError(f"建议只能转成 applied 或 dismissed：{status!r}")
    with session_scope(engine) as db:
        row = db.get(Suggestion, suggestion_id)
        if row is None:
            raise KeyError(suggestion_id)
        if row.status != "open":
            raise SuggestionStateError(f"这条建议已经是 {row.status}，不能再处理")
        row.status = status
        db.flush()
        return _to_value(row)


def list_turn_suggestions(engine: Engine, turn_id: str) -> list[SuggestionValue]:
    """某一轮产生的全部建议，按创建时间升序（TurnRunner 据此给每条建议发 `suggestion` 事件）。"""
    with session_scope(engine) as db:
        rows = db.scalars(
            select(Suggestion)
            .where(Suggestion.turn_id == turn_id)
            .order_by(Suggestion.created_at.asc(), Suggestion.id.asc())
        ).all()
        return [_to_value(row) for row in rows]


def count_open_by_target_stage(engine: Engine, project_id: str) -> dict[str, int]:
    """项目里每个目标阶段还有几条 `open` 的建议（阶段导航角标用）；没有的阶段不出现。"""
    with session_scope(engine) as db:
        rows = db.execute(
            select(Suggestion.to_stage, func.count())
            .where(Suggestion.project_id == project_id, Suggestion.status == "open")
            .group_by(Suggestion.to_stage)
        ).all()
        return {stage: int(count) for stage, count in rows}


def update_suggestion_status(engine: Engine, suggestion_id: str, status: str) -> SuggestionValue:
    """不检查当前状态地改状态（历史函数，保留给测试造数据）；正常处理走 `resolve_suggestion`。"""
    with session_scope(engine) as db:
        row = db.get(Suggestion, suggestion_id)
        if row is None:
            raise KeyError(suggestion_id)
        row.status = status
        db.flush()
        return _to_value(row)


def delete_suggestions(engine: Engine, project_id: str) -> None:
    """删除项目的全部回退建议（删除项目时用）；没有建议时是空操作。"""
    with session_scope(engine) as db:
        db.execute(delete(Suggestion).where(Suggestion.project_id == project_id))
