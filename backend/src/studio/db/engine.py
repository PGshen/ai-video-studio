"""SQLite 引擎、短事务上下文管理器与迁移入口（设计 §3.1、§7）。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def make_engine(db_path: str | Path) -> Engine:
    """创建 SQLite 引擎，连接时设置 WAL、busy_timeout、关闭外键约束。"""
    resolved = Path(db_path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{resolved}", future=True)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """一次一个短事务：成功提交，异常回滚，结束后关闭。"""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return config


def migrate(engine: Engine) -> None:
    """程序化执行 `alembic upgrade head`，复用调用方传入的引擎连接。

    复用已有连接（而不是让 alembic 用 URL 另开一个连接）是为了保证迁移里创建
    的表也在同一个已经设置好 PRAGMA 的连接上执行；见 `db/migrations/env.py`。
    """
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
