"""Alembic 环境：由 `studio.db.engine.migrate()` 程序化调用。

不使用 `alembic.ini`：`Config` 对象和 `script_location` 都在 `engine.py` 里
构造。迁移复用调用方传入的连接（`config.attributes["connection"]`），离线模式
和独立 CLI 调用不在本项目的使用场景内，因此不实现。
"""

from __future__ import annotations

from alembic import context

from studio.db.models import Base

target_metadata = Base.metadata


def run_migrations() -> None:
    connection = context.config.attributes.get("connection")
    if connection is None:
        raise RuntimeError(
            "本项目的迁移只支持通过 studio.db.engine.migrate(engine) 调用，"
            "需要在 config.attributes['connection'] 中提供已打开的连接。"
        )

    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
