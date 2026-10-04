"""风格库改用磁盘目录：`style_presets` 表导出成 `<数据目录>/styles/<id>/`，成功后删表（ADR 0019）。

导出放在迁移里（而不是 api 的 lifespan）：api 和 worker 两个进程启动时都会 `migrate()`，
谁先跑都不能在导出之前删表。数据目录取数据库文件所在的目录（`make_engine(data_dir / "studio.db")`
的约定）。导出有问题时迁移失败、旧表保留；已导出的目录下次会被跳过。不提供降级。

迁移里 import 了 `studio.db.legacy_style_table`（只依赖 `studio.styles` 这个纯能力层）。

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

from studio.db.legacy_style_table import export_style_table

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("style_presets"):
        return
    database = bind.engine.url.database
    data_dir = Path(database).parent if database and database != ":memory:" else None
    export_style_table(bind, data_dir)
    op.drop_table("style_presets")


def downgrade() -> None:
    raise NotImplementedError("风格已迁移到磁盘目录，不支持降级")
