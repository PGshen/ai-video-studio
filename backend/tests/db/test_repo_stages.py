from __future__ import annotations

from sqlalchemy import Engine

from studio.db.repo.profiles import get_model_profile, get_model_profile_by_id, seed_model_profiles
from studio.db.repo.stages import create_stage, delete_stages, get_stage, list_stages, update_stage


def test_create_get_list_update_stage(migrated_engine: Engine) -> None:
    create_stage(migrated_engine, project_id="p1", stage="topic", status="active")
    create_stage(migrated_engine, project_id="p1", stage="narrative", status="locked")
    create_stage(migrated_engine, project_id="p2", stage="topic", status="active")

    assert [s.stage for s in list_stages(migrated_engine, "p1")] == ["topic", "narrative"]

    update_stage(migrated_engine, "p1", "topic", status="finalized", finalized_snapshot_id="snap-1")
    topic = get_stage(migrated_engine, "p1", "topic")
    assert topic is not None
    assert (topic.status, topic.finalized_snapshot_id) == ("finalized", "snap-1")
    assert topic.finalized_at is None
    assert get_stage(migrated_engine, "p1", "animation") is None


def test_delete_stages_removes_all_rows_for_project(migrated_engine: Engine) -> None:
    create_stage(migrated_engine, project_id="p1", stage="topic", status="active")
    create_stage(migrated_engine, project_id="p1", stage="narrative", status="locked")
    create_stage(migrated_engine, project_id="p2", stage="topic", status="active")

    delete_stages(migrated_engine, "p1")

    assert list_stages(migrated_engine, "p1") == []
    assert [s.stage for s in list_stages(migrated_engine, "p2")] == ["topic"]
    # deleting a project with no stage rows is a no-op, not an error.
    delete_stages(migrated_engine, "never-existed")


def test_get_model_profile_by_id(migrated_engine: Engine) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=True)
    fake = get_model_profile(migrated_engine, "fake")
    assert fake is not None
    assert get_model_profile_by_id(migrated_engine, fake.id) == fake
    assert get_model_profile_by_id(migrated_engine, "nope") is None
