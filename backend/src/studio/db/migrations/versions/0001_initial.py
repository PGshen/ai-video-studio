"""初始迁移：创建设计 §3.1 的全部 12 张表。

Revision ID: 0001
Revises:
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ideas",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, nullable=True),
        sa.Column("source_session_id", sa.String, nullable=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("pitch", sa.String, nullable=True),
        sa.Column("counterintuitive", sa.String, nullable=True),
        sa.Column("tags", sa.JSON, nullable=True),
        sa.Column("scores", sa.JSON, nullable=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("idea_id", sa.String, nullable=True),
        sa.Column("current_stage", sa.String, nullable=False),
        sa.Column("settings", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "project_stages",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, nullable=False),
        sa.Column("stage", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("finalized_snapshot_id", sa.String, nullable=True),
        sa.Column("based_on_snapshot_id", sa.String, nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, nullable=True),
        sa.Column("stage", sa.String, nullable=False),
        sa.Column("model_profile_id", sa.String, nullable=False),
        sa.Column("runtime", sa.String, nullable=False),
        sa.Column("sdk_ref", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("title", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "turns",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("session_id", sa.String, nullable=False),
        sa.Column("user_message", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("start_snapshot_id", sa.String, nullable=True),
        sa.Column("end_snapshot_id", sa.String, nullable=True),
        sa.Column("usage", sa.JSON, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "turn_events",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("turn_id", sa.String, nullable=False),
        sa.Column("session_id", sa.String, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_turn_events_session_seq",
        "turn_events",
        ["session_id", "seq"],
    )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, nullable=False),
        sa.Column("manifest", sa.JSON, nullable=False),
        sa.Column("reason", sa.String, nullable=False),
        sa.Column("turn_id", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "suggestions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("project_id", sa.String, nullable=False),
        sa.Column("from_stage", sa.String, nullable=False),
        sa.Column("to_stage", sa.String, nullable=False),
        sa.Column("content", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("turn_id", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("project_id", sa.String, nullable=False),
        sa.Column("payload", sa.JSON, nullable=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("progress", sa.Float, nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "model_profiles",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("provider", sa.String, nullable=False),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("runtime", sa.String, nullable=False),
        sa.Column("base_url", sa.String, nullable=True),
        sa.Column("api_key_env", sa.String, nullable=True),
        sa.Column("supports_vision", sa.Boolean, nullable=False),
        sa.Column("price_input", sa.Float, nullable=True),
        sa.Column("price_output", sa.Float, nullable=True),
        sa.Column("max_cost_per_turn", sa.Float, nullable=True),
        sa.Column("max_steps_per_turn", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "style_presets",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("content", sa.String, nullable=False),
        sa.Column("exemplars", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("value", sa.JSON, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("style_presets")
    op.drop_table("model_profiles")
    op.drop_table("jobs")
    op.drop_table("suggestions")
    op.drop_table("snapshots")
    op.drop_index("ix_turn_events_session_seq", table_name="turn_events")
    op.drop_table("turn_events")
    op.drop_table("turns")
    op.drop_table("sessions")
    op.drop_table("project_stages")
    op.drop_table("projects")
    op.drop_table("ideas")
