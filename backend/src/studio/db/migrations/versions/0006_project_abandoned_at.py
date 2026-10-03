"""`projects` 加 `abandoned_at` 列（手动标记已废弃），并回填 `current_stage`。

此前没有任何代码在阶段定稿/重新打开后更新 `projects.current_stage`，存量项目一直停在
`topic`。这里按 `project_stages` 重新算一遍：第一个未定稿的阶段，全部定稿则是最后一个阶段
（规则同 `studio.agent.stage_flow.current_stage_of`，迁移里不 import 应用代码，所以再写一遍）。

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT project_id, stage, status FROM project_stages ORDER BY created_at, rowid")
    ).all()
    stages_by_project: dict[str, list[tuple[str, str]]] = {}
    for project_id, stage, status in rows:
        stages_by_project.setdefault(project_id, []).append((stage, status))
    for project_id, stages in stages_by_project.items():
        current = next((stage for stage, status in stages if status != "finalized"), stages[-1][0])
        connection.execute(
            sa.text("UPDATE projects SET current_stage = :stage WHERE id = :id"),
            {"stage": current, "id": project_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("abandoned_at")
