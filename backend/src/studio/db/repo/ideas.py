"""`ideas` 仓储：选题池卡片（设计 §3.1、§5.0；计划 M4 T2）。

校验规则放在这里的纯函数里，头脑风暴工具（T4）和 REST 接口共用：
- 标题：去首尾空白后 1–200 字；重复判定用 `normalize_title`（NFKC、大小写不敏感、
  空白折叠），归档的卡片也参与查重。
- 评分：只接受 `SCORE_KEYS` 里的四个维度，值为 1–5 的整数（`4.0` 这样的整数值浮点
  数按整数收）；缺省的维度不算错。
- 标签：字符串列表，去空白、去重，最多 `MAX_TAGS` 个。
- 状态：`idea`/`archived`。一张卡片可以创建任意多个项目（关联在 `projects.idea_id`），
  创建项目不改变卡片状态（ADR 0017）。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import Engine, select

from studio.db.engine import session_scope
from studio.db.models import Idea

SCORE_KEYS: Final = ("counterintuitive", "provable", "visual", "novelty")
"""反直觉、可论证、可视化、新鲜度（设计 §3.1）。"""
MAX_TAGS: Final = 8
MAX_TITLE_CHARS: Final = 200
MAX_TEXT_CHARS: Final = 1000


class IdeaValidationError(ValueError):
    """字段不合法（API 映射为 422）。"""


class IdeaNotFoundError(LookupError):
    pass


class DuplicateIdeaError(RuntimeError):
    """标题与已有卡片重复；`existing` 是那张卡片（API 映射为 409）。"""

    def __init__(self, existing: IdeaValue) -> None:
        super().__init__(f"已有相同标题的卡片：{existing.title}（id {existing.id}）")
        self.existing = existing


@dataclass(frozen=True, slots=True)
class IdeaValue:
    id: str
    source_session_id: str | None
    title: str
    pitch: str | None
    counterintuitive: str | None
    tags: list[str]
    scores: dict[str, int]
    status: str
    created_at: datetime
    updated_at: datetime


class _Unset:
    """`update_idea` 里区分「没传」和「传了 None（清空）」。"""

    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = _Unset()


def _to_value(row: Idea) -> IdeaValue:
    return IdeaValue(
        id=row.id,
        source_session_id=row.source_session_id,
        title=row.title,
        pitch=row.pitch,
        counterintuitive=row.counterintuitive,
        tags=list(row.tags or []),
        scores=dict(row.scores or {}),
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---- validation -----------------------------------------------------------


def normalize_title(title: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", title).casefold().split())


def _clean_title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        raise IdeaValidationError("标题不能为空")
    if len(cleaned) > MAX_TITLE_CHARS:
        raise IdeaValidationError(f"标题不能超过 {MAX_TITLE_CHARS} 字")
    return cleaned


def _clean_text(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) > MAX_TEXT_CHARS:
        raise IdeaValidationError(f"{name}不能超过 {MAX_TEXT_CHARS} 字")
    return cleaned or None


def clean_scores(raw: object) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise IdeaValidationError("scores 必须是对象")
    cleaned: dict[str, int] = {}
    for key, value in raw.items():
        if key not in SCORE_KEYS:
            raise IdeaValidationError(f"未知的评分维度：{key}（可用：{'、'.join(SCORE_KEYS)}）")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise IdeaValidationError(f"评分 {key} 必须是 1–5 的整数")
        if isinstance(value, float):
            if not value.is_integer():
                raise IdeaValidationError(f"评分 {key} 必须是 1–5 的整数")
            value = int(value)
        if not 1 <= value <= 5:
            raise IdeaValidationError(f"评分 {key} 必须在 1–5 之间，收到 {value}")
        cleaned[key] = value
    return cleaned


def clean_tags(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
        raise IdeaValidationError("tags 必须是字符串列表")
    cleaned: list[str] = []
    for tag in raw:
        stripped = tag.strip()
        if stripped and stripped not in cleaned:
            cleaned.append(stripped)
    if len(cleaned) > MAX_TAGS:
        raise IdeaValidationError(f"标签最多 {MAX_TAGS} 个")
    return cleaned


# ---- queries ----------------------------------------------------------------


def find_duplicate(
    engine: Engine, title: str, *, exclude_id: str | None = None
) -> IdeaValue | None:
    key = normalize_title(title)
    with session_scope(engine) as db:
        for row in db.scalars(select(Idea).order_by(Idea.created_at)):
            if row.id != exclude_id and normalize_title(row.title) == key:
                return _to_value(row)
    return None


def get_idea(engine: Engine, idea_id: str) -> IdeaValue | None:
    with session_scope(engine) as db:
        row = db.get(Idea, idea_id)
        return _to_value(row) if row is not None else None


def list_ideas(engine: Engine, *, status: str | None = None) -> list[IdeaValue]:
    """`status=None` 返回未归档（`idea`）；`"all"` 返回全部；其余按状态精确筛选。
    按创建时间倒序。
    """
    stmt = select(Idea).order_by(Idea.created_at.desc(), Idea.id.desc())
    if status is None:
        stmt = stmt.where(Idea.status == "idea")
    elif status != "all":
        stmt = stmt.where(Idea.status == status)
    with session_scope(engine) as db:
        return [_to_value(row) for row in db.scalars(stmt)]


# ---- writes -------------------------------------------------------------------


def create_idea(
    engine: Engine,
    *,
    title: str,
    pitch: str | None = None,
    counterintuitive: str | None = None,
    tags: list[str] | None = None,
    scores: dict[str, Any] | None = None,
    source_session_id: str | None = None,
) -> IdeaValue:
    cleaned_title = _clean_title(title)
    values = {
        "pitch": _clean_text("一句话卖点", pitch),
        "counterintuitive": _clean_text("反直觉点", counterintuitive),
        "tags": clean_tags(tags),
        "scores": clean_scores(scores),
    }
    duplicate = find_duplicate(engine, cleaned_title)
    if duplicate is not None:
        raise DuplicateIdeaError(duplicate)
    with session_scope(engine) as db:
        row = Idea(title=cleaned_title, source_session_id=source_session_id, **values)
        db.add(row)
        db.flush()
        return _to_value(row)


def update_idea(
    engine: Engine,
    idea_id: str,
    *,
    title: str | _Unset = UNSET,
    pitch: str | None | _Unset = UNSET,
    counterintuitive: str | None | _Unset = UNSET,
    tags: list[str] | _Unset = UNSET,
    scores: dict[str, Any] | _Unset = UNSET,
    status: str | _Unset = UNSET,
) -> IdeaValue:
    """只改传入的字段。`status` 只接受 `idea`/`archived`。"""
    current = get_idea(engine, idea_id)
    if current is None:
        raise IdeaNotFoundError(idea_id)
    changes: dict[str, Any] = {}
    if not isinstance(status, _Unset):
        if status not in ("idea", "archived"):
            raise IdeaValidationError("状态只能在 idea 和 archived 之间切换")
        changes["status"] = status
    if not isinstance(title, _Unset):
        cleaned = _clean_title(title)
        duplicate = find_duplicate(engine, cleaned, exclude_id=idea_id)
        if duplicate is not None:
            raise DuplicateIdeaError(duplicate)
        changes["title"] = cleaned
    if not isinstance(pitch, _Unset):
        changes["pitch"] = _clean_text("一句话卖点", pitch)
    if not isinstance(counterintuitive, _Unset):
        changes["counterintuitive"] = _clean_text("反直觉点", counterintuitive)
    if not isinstance(tags, _Unset):
        changes["tags"] = clean_tags(tags)
    if not isinstance(scores, _Unset):
        changes["scores"] = clean_scores(scores)
    if not changes:
        return current
    with session_scope(engine) as db:
        row = db.get(Idea, idea_id)
        if row is None:
            raise IdeaNotFoundError(idea_id)
        for name, value in changes.items():
            setattr(row, name, value)
        db.flush()
        return _to_value(row)
