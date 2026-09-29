from __future__ import annotations

from sqlalchemy import Engine

from studio.db.repo.suggestions import (
    create_suggestion,
    get_suggestion,
    list_suggestions,
    update_suggestion_status,
)


def test_create_suggestion_defaults_to_open_status(migrated_engine: Engine) -> None:
    suggestion = create_suggestion(
        migrated_engine,
        project_id="proj-1",
        from_stage="animation",
        to_stage="narrative",
        content="s-hook 的旁白和画面对不上，建议改一下这句台词。",
        turn_id="turn-1",
    )

    assert suggestion.status == "open"
    assert suggestion.project_id == "proj-1"
    assert suggestion.from_stage == "animation"
    assert suggestion.to_stage == "narrative"
    assert suggestion.content == "s-hook 的旁白和画面对不上，建议改一下这句台词。"
    assert suggestion.turn_id == "turn-1"

    fetched = get_suggestion(migrated_engine, suggestion.id)
    assert fetched is not None
    assert (fetched.id, fetched.status, fetched.content) == (
        suggestion.id,
        suggestion.status,
        suggestion.content,
    )


def test_get_suggestion_returns_none_when_missing(migrated_engine: Engine) -> None:
    assert get_suggestion(migrated_engine, "never-existed") is None


def test_list_suggestions_filters_by_project_and_status(migrated_engine: Engine) -> None:
    a = create_suggestion(
        migrated_engine,
        project_id="proj-1",
        from_stage="animation",
        to_stage="narrative",
        content="建议 A",
        turn_id=None,
    )
    create_suggestion(
        migrated_engine,
        project_id="proj-1",
        from_stage="animation",
        to_stage="narrative",
        content="建议 B",
        turn_id=None,
    )
    create_suggestion(
        migrated_engine,
        project_id="proj-2",
        from_stage="animation",
        to_stage="narrative",
        content="建议 C",
        turn_id=None,
    )

    assert {s.content for s in list_suggestions(migrated_engine, "proj-1")} == {"建议 A", "建议 B"}
    assert [s.content for s in list_suggestions(migrated_engine, "proj-2")] == ["建议 C"]

    update_suggestion_status(migrated_engine, a.id, "dismissed")
    open_only = list_suggestions(migrated_engine, "proj-1", status="open")
    assert [s.content for s in open_only] == ["建议 B"]


def test_update_suggestion_status_changes_status_and_persists(migrated_engine: Engine) -> None:
    suggestion = create_suggestion(
        migrated_engine,
        project_id="proj-1",
        from_stage="animation",
        to_stage="narrative",
        content="建议 A",
        turn_id=None,
    )

    updated = update_suggestion_status(migrated_engine, suggestion.id, "applied")

    assert updated.status == "applied"
    fetched = get_suggestion(migrated_engine, suggestion.id)
    assert fetched is not None
    assert fetched.status == "applied"
