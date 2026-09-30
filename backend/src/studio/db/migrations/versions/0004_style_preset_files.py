"""`style_presets` 加 `description`、`reference_files` 两列：风格以 skill 形态的目录存放（M5 T2）。

两列都可空，旧行不受影响。

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("style_presets", sa.Column("description", sa.String, nullable=True))
    op.add_column("style_presets", sa.Column("reference_files", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("style_presets", "reference_files")
    op.drop_column("style_presets", "description")
