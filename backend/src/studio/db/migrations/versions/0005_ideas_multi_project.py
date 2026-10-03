"""一张想法卡片可以创建多个项目：去掉 `ideas.project_id` 和 `picked` 状态（ADR 0017）。

卡片和项目的关联只剩 `projects.idea_id`（一对多）。旧的 `picked` 卡片回到 `idea`；
`ideas.project_id` 的信息本来就在对应项目的 `idea_id` 里，直接丢弃。

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE ideas SET status = 'idea' WHERE status = 'picked'")
    with op.batch_alter_table("ideas") as batch:
        batch.drop_column("project_id")


def downgrade() -> None:
    # `picked` 状态无法还原（不知道哪些 `idea` 原来是 `picked`），只补回列。
    with op.batch_alter_table("ideas") as batch:
        batch.add_column(sa.Column("project_id", sa.String, nullable=True))
