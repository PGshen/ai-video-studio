"""`project_stages`：单个 `based_on_snapshot_id` 换成按上游记录的 `based_on`（JSON）。

阶段可以有多个上游（多形态视频流水线，设计 §3.3），下游需要分别记住每个上游所基于的
定稿快照：`based_on = {上游阶段名: 快照 id}`。

回填：迁移前只有 `narrative`（上游 `topic`）和 `animation`（上游 `narrative`）两种有上游的
阶段，`based_on_snapshot_id` 非空时分别写成 `{"topic": id}`、`{"narrative": id}`；其余为 `{}`。
降级时取 `based_on` 中任意一个值写回旧列。

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-04
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Stages that had an upstream before 0009, and that upstream (migrations do not import app code).
_LEGACY_UPSTREAM = {"narrative": "topic", "animation": "narrative"}


def upgrade() -> None:
    op.add_column(
        "project_stages",
        sa.Column("based_on", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, stage, based_on_snapshot_id FROM project_stages "
            "WHERE based_on_snapshot_id IS NOT NULL"
        )
    ).all()
    for stage_id, stage, snapshot_id in rows:
        upstream = _LEGACY_UPSTREAM.get(stage)
        if upstream is None:
            continue
        connection.execute(
            sa.text("UPDATE project_stages SET based_on = :based_on WHERE id = :id"),
            {"based_on": json.dumps({upstream: snapshot_id}), "id": stage_id},
        )
    with op.batch_alter_table("project_stages") as batch:
        batch.drop_column("based_on_snapshot_id")


def downgrade() -> None:
    op.add_column("project_stages", sa.Column("based_on_snapshot_id", sa.String(), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, based_on FROM project_stages")).all()
    for stage_id, raw in rows:
        based_on = json.loads(raw) if isinstance(raw, str) else (raw or {})
        snapshot_id = next(iter(based_on.values()), None)
        if snapshot_id is None:
            continue
        connection.execute(
            sa.text("UPDATE project_stages SET based_on_snapshot_id = :sid WHERE id = :id"),
            {"sid": snapshot_id, "id": stage_id},
        )
    with op.batch_alter_table("project_stages") as batch:
        batch.drop_column("based_on")
