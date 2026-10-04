"""`sessions` 加 `subject_id` 列：会话可以属于一套风格（风格对话，ADR 0019）。

风格会话没有项目（`project_id` 为空，`stage = 'style'`），`subject_id` 是风格 id；创建会话时
「取消同组活动会话」的分组条件是 `项目 + 阶段 + subject_id`。其他会话该列为空。

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("subject_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("subject_id")
