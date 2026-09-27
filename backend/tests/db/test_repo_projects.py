from __future__ import annotations

from sqlalchemy import Engine

from studio.db.repo.projects import create_project, get_project


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
