from __future__ import annotations

from sqlalchemy import Engine

from studio.db.repo.snapshots import (
    delete_snapshots,
    insert_snapshot,
    latest_snapshot,
    list_snapshots,
)


def test_delete_snapshots_removes_all_rows_for_project(migrated_engine: Engine) -> None:
    insert_snapshot(migrated_engine, project_id="p1", manifest={"a": "sha-a"}, reason="init")
    insert_snapshot(migrated_engine, project_id="p1", manifest={"a": "sha-b"}, reason="turn")
    insert_snapshot(migrated_engine, project_id="p2", manifest={"b": "sha-c"}, reason="init")

    delete_snapshots(migrated_engine, "p1")

    assert list_snapshots(migrated_engine, "p1") == []
    assert [s.reason for s in list_snapshots(migrated_engine, "p2")] == ["init"]
    # deleting a project with no snapshot rows is a no-op, not an error.
    delete_snapshots(migrated_engine, "never-existed")


def test_timestamps_from_one_process_are_strictly_increasing() -> None:
    """windows-native T10: Python 3.12 on Windows reads a coarse wall clock (~1–16 ms), so rows
    created back to back used to share `created_at` and "latest"/"before" became ambiguous."""
    from studio.db.models import _utcnow

    stamps = [_utcnow() for _ in range(2000)]
    assert all(a < b for a, b in zip(stamps, stamps[1:], strict=False))


def test_latest_snapshot_is_the_last_one_created_even_within_one_clock_tick(
    migrated_engine: Engine,
) -> None:
    for i in range(30):
        insert_snapshot(migrated_engine, project_id="p1", manifest={"a": str(i)}, reason="turn")
        latest = latest_snapshot(migrated_engine, "p1")
        assert latest is not None and latest.manifest == {"a": str(i)}
