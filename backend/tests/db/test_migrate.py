from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import Engine, inspect, text

from studio.db.engine import _alembic_config, make_engine, migrate

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
    "settings",
}


def test_migrate_creates_all_11_tables(migrated_engine: Engine) -> None:
    tables = set(inspect(migrated_engine).get_table_names())
    assert EXPECTED_TABLES <= tables
    assert len(EXPECTED_TABLES) == 11
    assert "style_presets" not in tables  # styles live in data/styles/ since 0007


def test_migrate_is_idempotent(migrated_engine: Engine) -> None:
    # 再次执行不应报错，也不应改变表结构
    migrate(migrated_engine)
    tables = set(inspect(migrated_engine).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_migrate_creates_turn_events_session_seq_index(migrated_engine: Engine) -> None:
    indexes = inspect(migrated_engine).get_indexes("turn_events")
    columns_by_index = {tuple(ix["column_names"]) for ix in indexes}
    assert ("session_id", "seq") in columns_by_index


def test_migrate_adds_projects_completed_at_column(migrated_engine: Engine) -> None:
    columns = {col["name"] for col in inspect(migrated_engine).get_columns("projects")}
    assert "completed_at" in columns


def test_migrate_runs_on_fresh_db_file(db_path: Path) -> None:
    engine = make_engine(db_path)
    try:
        migrate(engine)
        assert db_path.exists()
        tables = set(inspect(engine).get_table_names())
        assert EXPECTED_TABLES <= tables
    finally:
        engine.dispose()


def test_0005_turns_picked_ideas_back_into_ideas_and_drops_project_id(engine: Engine) -> None:
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0004")
        connection.execute(
            text(
                "INSERT INTO ideas (id, title, status, project_id, created_at, updated_at) VALUES "
                "('i1', 'A', 'picked', 'p1', '2026-10-01', '2026-10-01'), "
                "('i2', 'B', 'archived', NULL, '2026-10-01', '2026-10-01')"
            )
        )
        command.upgrade(config, "head")
        rows = dict(connection.execute(text("SELECT id, status FROM ideas")).all())
    assert rows == {"i1": "idea", "i2": "archived"}
    assert "project_id" not in {col["name"] for col in inspect(engine).get_columns("ideas")}


def test_0006_adds_abandoned_at_and_backfills_current_stage(engine: Engine) -> None:
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0005")
        for pid, stages in {
            "p-new": ("active", "locked", "locked"),
            "p-mid": ("finalized", "active", "locked"),
            "p-done": ("finalized", "finalized", "finalized"),
            "p-reopened": ("active", "active", "finalized"),
        }.items():
            connection.execute(
                text(
                    "INSERT INTO projects (id, title, current_stage, settings, created_at, "
                    "updated_at) VALUES (:id, 't', 'topic', '{}', '2026-10-01', '2026-10-01')"
                ),
                {"id": pid},
            )
            names = ("topic", "narrative", "animation")
            for index, (stage, status) in enumerate(zip(names, stages, strict=True)):
                connection.execute(
                    text(
                        "INSERT INTO project_stages (id, project_id, stage, status, created_at, "
                        "updated_at) VALUES (:id, :pid, :stage, :status, :at, :at)"
                    ),
                    {
                        "id": f"{pid}-{stage}",
                        "pid": pid,
                        "stage": stage,
                        "status": status,
                        "at": f"2026-10-01 00:00:0{index}",
                    },
                )
        command.upgrade(config, "head")
        rows = dict(connection.execute(text("SELECT id, current_stage FROM projects")).all())
    assert rows == {
        "p-new": "topic",
        "p-mid": "narrative",
        "p-done": "animation",
        "p-reopened": "topic",
    }
    assert "abandoned_at" in {col["name"] for col in inspect(engine).get_columns("projects")}
