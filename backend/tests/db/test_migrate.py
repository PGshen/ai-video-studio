from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, inspect

from studio.db.engine import make_engine, migrate

EXPECTED_TABLES = {
    "ideas",
    "projects",
    "project_stages",
    "sessions",
    "turns",
    "turn_events",
    "snapshots",
    "suggestions",
    "jobs",
    "model_profiles",
    "style_presets",
    "settings",
}


def test_migrate_creates_all_12_tables(migrated_engine: Engine) -> None:
    tables = set(inspect(migrated_engine).get_table_names())
    assert EXPECTED_TABLES <= tables
    assert len(EXPECTED_TABLES) == 12


def test_migrate_is_idempotent(migrated_engine: Engine) -> None:
    # 再次执行不应报错，也不应改变表结构
    migrate(migrated_engine)
    tables = set(inspect(migrated_engine).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_migrate_creates_turn_events_session_seq_index(migrated_engine: Engine) -> None:
    indexes = inspect(migrated_engine).get_indexes("turn_events")
    columns_by_index = {tuple(ix["column_names"]) for ix in indexes}
    assert ("session_id", "seq") in columns_by_index


def test_migrate_runs_on_fresh_db_file(db_path: Path) -> None:
    engine = make_engine(db_path)
    try:
        migrate(engine)
        assert db_path.exists()
        tables = set(inspect(engine).get_table_names())
        assert EXPECTED_TABLES <= tables
    finally:
        engine.dispose()
