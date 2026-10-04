"""`project_stages` 加 `stale_from` 列：阶段变为 `stale` 之前的状态（TD-65）。

上游改回原样、下游恢复时据此回到 `finalized` 或 `active`。已有的 `stale` 行为空，
恢复时按 `active` 处理（与迁移前行为一致）。

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("project_stages", sa.Column("stale_from", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project_stages") as batch:
        batch.drop_column("stale_from")
