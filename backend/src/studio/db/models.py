"""设计 §3.1 全部 12 张表的 SQLAlchemy ORM 模型。

主键统一为字符串 id（`uuid4().hex`），时间统一存 UTC。表之间不设外键约束
（PRAGMA `foreign_keys=OFF`），关联在应用层维护（设计 §3.1 说明）。
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _new_id() -> str:
    return uuid4().hex


_last_now = datetime.min.replace(tzinfo=UTC)
_now_lock = threading.Lock()


def _utcnow() -> datetime:
    """`created_at`/`updated_at` default, strictly increasing within this process.

    Python 3.12 on Windows reads a coarse wall clock (`GetSystemTimeAsFileTime`, ~1–16 ms), so
    rows created back to back shared a timestamp and "latest"/"before this one" queries picked
    an arbitrary row (windows-native T10). A tie is bumped by one microsecond.
    """
    global _last_now
    with _now_lock:
        now = datetime.now(UTC)
        if now <= _last_now:
            now = _last_now + timedelta(microseconds=1)
        _last_now = now
        return now


class Base(DeclarativeBase):
    pass


class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    source_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    pitch: Mapped[str | None] = mapped_column(String, nullable=True)
    counterintuitive: Mapped[str | None] = mapped_column(String, nullable=True)
    tags: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="idea")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String, nullable=False)
    idea_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_stage: Mapped[str] = mapped_column(String, nullable=False, default="topic")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """项目"成片定稿"后写入（T11），或用户手动标记已完成；`None` 表示尚未完成。"""
    abandoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """用户手动标记已废弃的时间；与 `completed_at` 互斥（`repo.projects.set_project_status`）。"""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class ProjectStage(Base):
    __tablename__ = "project_stages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="locked")
    finalized_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    based_on: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    """每个上游所基于的定稿快照：`{上游阶段名: 快照 id}`（0009）。"""
    stale_from: Mapped[str | None] = mapped_column(String, nullable=True)
    """变为 `stale` 之前的状态（`active`/`finalized`），恢复时回到它（0010）。"""
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String, nullable=True)
    """会话属于的对象：风格对话是风格 id，其余会话为空（0008）。"""
    model_profile_id: Mapped[str] = mapped_column(String, nullable=False)
    runtime: Mapped[str] = mapped_column(String, nullable=False)
    sdk_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="idle")
    is_active: Mapped[bool] = mapped_column(default=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    user_message: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    start_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    end_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    """用户消息带的附件记录（迁移 0011）；旧行为空。"""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class TurnEvent(Base):
    """一轮内持久化的事件。

    `seq` 是会话内单调递增的序号（决策记录 2026-09-26），不是 turn 内的序号，
    这样 SSE `after_seq` 续传只需要认识会话，不需要关心事件属于哪个 turn。
    为此本表冗余存储 `session_id`（可从 `turn_id` 关联 `turns.session_id` 推出，
    但直接存一份可以避免续传查询时联表）。`(session_id, seq)` 唯一（迁移 0002）。
    """

    __tablename__ = "turn_events"
    __table_args__ = (Index("uq_turn_events_session_seq", "session_id", "seq", unique=True),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    turn_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    manifest: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    from_stage: Mapped[str] = mapped_column(String, nullable=False)
    to_stage: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    turn_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    type: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class ModelProfile(Base):
    __tablename__ = "model_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    runtime: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key_env: Mapped[str | None] = mapped_column(String, nullable=True)
    supports_vision: Mapped[bool] = mapped_column(default=False)
    price_input: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_output: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_cost_per_turn: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_steps_per_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
