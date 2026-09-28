from __future__ import annotations

from sqlalchemy import Engine

from studio.db.repo.snapshots import delete_snapshots, insert_snapshot, list_snapshots


def test_delete_snapshots_removes_all_rows_for_project(migrated_engine: Engine) -> None:
    insert_snapshot(migrated_engine, project_id="p1", manifest={"a": "sha-a"}, reason="init")
    insert_snapshot(migrated_engine, project_id="p1", manifest={"a": "sha-b"}, reason="turn")
    insert_snapshot(migrated_engine, project_id="p2", manifest={"b": "sha-c"}, reason="init")

    delete_snapshots(migrated_engine, "p1")

    assert list_snapshots(migrated_engine, "p1") == []
    assert [s.reason for s in list_snapshots(migrated_engine, "p2")] == ["init"]
    # deleting a project with no snapshot rows is a no-op, not an error.
    delete_snapshots(migrated_engine, "never-existed")
