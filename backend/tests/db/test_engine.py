from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, text

from studio.db.engine import make_engine, session_scope


def _pragma(engine: Engine, name: str) -> object:
    with engine.connect() as conn:
        return conn.execute(text(f"PRAGMA {name}")).scalar()


def test_make_engine_sets_wal_journal_mode(db_path: Path) -> None:
    engine = make_engine(db_path)
    try:
        assert str(_pragma(engine, "journal_mode")).lower() == "wal"
    finally:
        engine.dispose()


def test_make_engine_sets_busy_timeout(db_path: Path) -> None:
    engine = make_engine(db_path)
    try:
        assert _pragma(engine, "busy_timeout") == 5000
    finally:
        engine.dispose()


def test_make_engine_disables_foreign_keys(db_path: Path) -> None:
    engine = make_engine(db_path)
    try:
        assert _pragma(engine, "foreign_keys") == 0
    finally:
        engine.dispose()


def test_make_engine_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "dir" / "studio.db"
    engine = make_engine(nested)
    try:
        assert nested.parent.is_dir()
    finally:
        engine.dispose()


def test_session_scope_commits_on_success(db_path: Path) -> None:
    engine = make_engine(db_path)
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE t (id INTEGER)"))
            session.execute(text("INSERT INTO t VALUES (1)"))

        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM t")).scalar() == 1
    finally:
        engine.dispose()


def test_session_scope_rolls_back_on_error(db_path: Path) -> None:
    engine = make_engine(db_path)
    try:
        with session_scope(engine) as session:
            session.execute(text("CREATE TABLE t (id INTEGER)"))

        try:
            with session_scope(engine) as session:
                session.execute(text("INSERT INTO t VALUES (1)"))
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM t")).scalar() == 0
    finally:
        engine.dispose()
