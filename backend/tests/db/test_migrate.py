from __future__ import annotations

import json
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


def test_0008_adds_a_nullable_subject_id_to_sessions_and_keeps_existing_rows(
    engine: Engine,
) -> None:
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0007")
        connection.execute(
            text(
                "INSERT INTO sessions (id, project_id, stage, model_profile_id, runtime, status, "
                "is_active, created_at, updated_at) VALUES ('s1', NULL, 'brainstorm', 'm', 'fake', "
                "'idle', 1, '2026-10-01', '2026-10-01')"
            )
        )
        command.upgrade(config, "head")
        rows = connection.execute(text("SELECT id, subject_id FROM sessions")).all()
    assert rows == [("s1", None)]
    assert "subject_id" in {col["name"] for col in inspect(engine).get_columns("sessions")}


def test_0009_backfills_based_on_from_based_on_snapshot_id_and_downgrade_restores_it(
    engine: Engine,
) -> None:
    config = _alembic_config()
    rows = (
        ("st-topic", "topic", None),
        ("st-narrative", "narrative", "snap-topic"),
        ("st-animation", "animation", "snap-narrative"),
    )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0008")
        for stage_id, stage, based_on in rows:
            connection.execute(
                text(
                    "INSERT INTO project_stages (id, project_id, stage, status, "
                    "based_on_snapshot_id, created_at, updated_at) VALUES "
                    "(:id, 'p1', :stage, 'active', :based_on, '2026-10-01', '2026-10-01')"
                ),
                {"id": stage_id, "stage": stage, "based_on": based_on},
            )

        command.upgrade(config, "0009")
        upgraded = {
            stage_id: json.loads(value)
            for stage_id, value in connection.execute(
                text("SELECT id, based_on FROM project_stages")
            ).all()
        }
        columns = {col["name"] for col in inspect(connection).get_columns("project_stages")}

        command.downgrade(config, "0008")
        downgraded = dict(
            connection.execute(text("SELECT id, based_on_snapshot_id FROM project_stages")).all()
        )
        old_columns = {col["name"] for col in inspect(connection).get_columns("project_stages")}

    assert upgraded == {
        "st-topic": {},
        "st-narrative": {"topic": "snap-topic"},
        "st-animation": {"narrative": "snap-narrative"},
    }
    assert "based_on" in columns and "based_on_snapshot_id" not in columns
    assert downgraded == {
        "st-topic": None,
        "st-narrative": "snap-topic",
        "st-animation": "snap-narrative",
    }
    assert "based_on_snapshot_id" in old_columns and "based_on" not in old_columns


def test_0010_adds_a_nullable_stale_from_to_project_stages_and_keeps_existing_rows(
    engine: Engine,
) -> None:
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0009")
        connection.execute(
            text(
                "INSERT INTO project_stages (id, project_id, stage, status, created_at, "
                "updated_at) VALUES ('st1', 'p1', 'narrative', 'stale', '2026-10-01', '2026-10-01')"
            )
        )
        command.upgrade(config, "0010")
        upgraded = connection.execute(
            text("SELECT id, status, stale_from FROM project_stages")
        ).all()
        command.downgrade(config, "0009")
        old_columns = {col["name"] for col in inspect(connection).get_columns("project_stages")}

    assert upgraded == [("st1", "stale", None)]
    assert "stale_from" not in old_columns


def test_0011_adds_a_nullable_attachments_column_to_turns_and_keeps_existing_rows(
    engine: Engine,
) -> None:
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0010")
        connection.execute(
            text(
                "INSERT INTO turns (id, session_id, user_message, status, created_at, "
                "updated_at) VALUES ('t1', 's1', 'hi', 'done', '2026-10-01', '2026-10-01')"
            )
        )
        command.upgrade(config, "0011")
        upgraded = connection.execute(text("SELECT id, attachments FROM turns")).all()
        command.downgrade(config, "0010")
        old_columns = {col["name"] for col in inspect(connection).get_columns("turns")}

    assert upgraded == [("t1", None)]
    assert "attachments" not in old_columns
