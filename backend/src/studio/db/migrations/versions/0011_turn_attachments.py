"""`turns` 加 `attachments` 列：这一轮用户消息带的附件记录（设计 2026-10-09 §5.5）。

JSON 列表，每项是 `api/attachments.AttachmentRecord.to_dict()`；旧行为空，读作 `[]`。

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("turns", sa.Column("attachments", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("turns") as batch:
        batch.drop_column("attachments")
