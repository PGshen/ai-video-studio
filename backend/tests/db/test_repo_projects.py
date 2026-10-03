from __future__ import annotations

import pytest
from sqlalchemy import Engine

from studio.db.repo.projects import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    mark_project_completed,
    set_current_stage,
    set_project_status,
    update_project_settings,
)


def test_create_project_returns_value_object_with_defaults(migrated_engine: Engine) -> None:
    project = create_project(migrated_engine, title="我的视频")
    assert project.title == "我的视频"
    assert project.id
    assert project.current_stage == "topic"
    assert project.idea_id is None
    assert project.settings == {}


def test_create_project_accepts_idea_id_and_settings(migrated_engine: Engine) -> None:
    project = create_project(
        migrated_engine,
        title="带选题",
        idea_id="idea-1",
        settings={"aspect_ratio": "16:9"},
    )
    assert project.idea_id == "idea-1"
    assert project.settings == {"aspect_ratio": "16:9"}


def test_get_project_returns_previously_created_project(migrated_engine: Engine) -> None:
    created = create_project(migrated_engine, title="项目 A")
    fetched = get_project(migrated_engine, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "项目 A"


def test_get_project_unknown_id_returns_none(migrated_engine: Engine) -> None:
    assert get_project(migrated_engine, "does-not-exist") is None


def test_create_project_ids_are_unique(migrated_engine: Engine) -> None:
    a = create_project(migrated_engine, title="A")
    b = create_project(migrated_engine, title="B")
    assert a.id != b.id


def test_get_project_returns_plain_value_not_orm(migrated_engine: Engine) -> None:
    from studio.db import models

    created = create_project(migrated_engine, title="项目 B")
    fetched = get_project(migrated_engine, created.id)
    assert not isinstance(fetched, models.Project)


def test_create_project_accepts_explicit_id(migrated_engine: Engine) -> None:
    project = create_project(migrated_engine, id="fixed-id", title="固定 id")
    assert project.id == "fixed-id"
    assert get_project(migrated_engine, "fixed-id") is not None


def test_list_projects_returns_all_newest_first(migrated_engine: Engine) -> None:
    a = create_project(migrated_engine, title="A")
    b = create_project(migrated_engine, title="B")
    ids = [p.id for p in list_projects(migrated_engine)]
    assert ids == [b.id, a.id]


def test_delete_project_removes_row_and_is_idempotent(migrated_engine: Engine) -> None:
    created = create_project(migrated_engine, title="待删除")
    delete_project(migrated_engine, created.id)
    assert get_project(migrated_engine, created.id) is None
    # deleting again (or an id that never existed) is a no-op, not an error.
    delete_project(migrated_engine, created.id)
    delete_project(migrated_engine, "never-existed")


def test_update_project_settings_merges_and_none_removes_a_key(migrated_engine: Engine) -> None:
    created = create_project(migrated_engine, title="P", settings={"style_name": "S", "voice": "a"})

    updated = update_project_settings(
        migrated_engine, created.id, {"voice": "b", "speech_rate": 1.2}
    )
    assert updated.settings == {"style_name": "S", "voice": "b", "speech_rate": 1.2}

    updated = update_project_settings(migrated_engine, created.id, {"voice": None})
    assert updated.settings == {"style_name": "S", "speech_rate": 1.2}
    assert get_project(migrated_engine, created.id) == updated


def test_update_project_settings_persists_across_reads(migrated_engine: Engine) -> None:
    """JSON 列是可变对象：就地修改不会被 SQLAlchemy 发现，必须整体替换才落库。"""
    created = create_project(migrated_engine, title="P")

    update_project_settings(migrated_engine, created.id, {"voice": "x"})
    update_project_settings(migrated_engine, created.id, {"speech_rate": 0.8})

    fetched = get_project(migrated_engine, created.id)
    assert fetched is not None and fetched.settings == {"voice": "x", "speech_rate": 0.8}


def test_update_project_settings_unknown_project(migrated_engine: Engine) -> None:
    with pytest.raises(LookupError):
        update_project_settings(migrated_engine, "nope", {"voice": "x"})


def test_new_project_is_active(migrated_engine: Engine) -> None:
    project = create_project(migrated_engine, title="A")
    assert (project.status, project.completed_at, project.abandoned_at) == ("active", None, None)


def test_set_project_status_keeps_the_states_mutually_exclusive(migrated_engine: Engine) -> None:
    project = create_project(migrated_engine, title="A")

    completed = set_project_status(migrated_engine, project.id, "completed")
    assert completed.status == "completed"
    assert completed.completed_at is not None and completed.abandoned_at is None

    abandoned = set_project_status(migrated_engine, project.id, "abandoned")
    assert abandoned.status == "abandoned"
    assert abandoned.abandoned_at is not None and abandoned.completed_at is None

    active = set_project_status(migrated_engine, project.id, "active")
    assert (active.status, active.completed_at, active.abandoned_at) == ("active", None, None)


def test_set_project_status_unknown_project_raises(migrated_engine: Engine) -> None:
    with pytest.raises(KeyError):
        set_project_status(migrated_engine, "nope", "completed")


def test_final_render_completion_revives_an_abandoned_project(migrated_engine: Engine) -> None:
    project = create_project(migrated_engine, title="A")
    set_project_status(migrated_engine, project.id, "abandoned")

    revived = mark_project_completed(migrated_engine, project.id)

    assert (revived.status, revived.abandoned_at) == ("completed", None)


def test_set_current_stage(migrated_engine: Engine) -> None:
    project = create_project(migrated_engine, title="A")
    assert set_current_stage(migrated_engine, project.id, "animation").current_stage == "animation"
    fetched = get_project(migrated_engine, project.id)
    assert fetched is not None and fetched.current_stage == "animation"
