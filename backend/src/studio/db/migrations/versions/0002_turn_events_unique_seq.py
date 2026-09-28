"""turn_events 的 (session_id, seq) 改为唯一索引。

T2 只建了非唯一索引；T6 开始由 TurnRunner 写入持久事件，`seq` 在插入事件的
同一个短事务里按"会话内 max+1"分配，唯一索引是防止重复序号的最后一道防线。
SQLite 不支持给已有表加约束，这里用删除旧索引 + 建唯一索引实现。

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_turn_events_session_seq", table_name="turn_events")
    op.create_index("uq_turn_events_session_seq", "turn_events", ["session_id", "seq"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_turn_events_session_seq", table_name="turn_events")
    op.create_index("ix_turn_events_session_seq", "turn_events", ["session_id", "seq"])
