from __future__ import annotations

import pytest
from sqlalchemy import Engine

from studio.db.repo.suggestions import (
    SuggestionStateError,
    count_open_by_target_stage,
    create_suggestion,
    get_suggestion,
    list_suggestions,
    list_turn_suggestions,
    resolve_suggestion,
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


def _new(
    engine: Engine, *, project: str = "p", to_stage: str = "narrative", turn: str | None = "t1"
):
    return create_suggestion(
        engine,
        project_id=project,
        from_stage="animation",
        to_stage=to_stage,
        content="x",
        turn_id=turn,
    )


class TestResolve:
    def test_open_can_be_applied_or_dismissed(self, migrated_engine: Engine) -> None:
        a, b = _new(migrated_engine), _new(migrated_engine)

        assert resolve_suggestion(migrated_engine, a.id, "applied").status == "applied"
        assert resolve_suggestion(migrated_engine, b.id, "dismissed").status == "dismissed"
        fetched = get_suggestion(migrated_engine, a.id)
        assert fetched is not None and fetched.status == "applied"

    @pytest.mark.parametrize("first", ["applied", "dismissed"])
    @pytest.mark.parametrize("second", ["applied", "dismissed"])
    def test_a_resolved_suggestion_cannot_be_resolved_again(
        self, migrated_engine: Engine, first: str, second: str
    ) -> None:
        suggestion = _new(migrated_engine)
        resolve_suggestion(migrated_engine, suggestion.id, first)

        with pytest.raises(SuggestionStateError):
            resolve_suggestion(migrated_engine, suggestion.id, second)

        fetched = get_suggestion(migrated_engine, suggestion.id)
        assert fetched is not None and fetched.status == first

    def test_only_applied_and_dismissed_are_valid_targets(self, migrated_engine: Engine) -> None:
        suggestion = _new(migrated_engine)

        for bad in ("open", "done", ""):
            with pytest.raises(ValueError):
                resolve_suggestion(migrated_engine, suggestion.id, bad)

    def test_unknown_id(self, migrated_engine: Engine) -> None:
        with pytest.raises(KeyError):
            resolve_suggestion(migrated_engine, "nope", "applied")


def test_list_turn_suggestions_returns_only_that_turns_in_creation_order(
    migrated_engine: Engine,
) -> None:
    first = _new(migrated_engine, turn="t1")
    _new(migrated_engine, turn="t2")
    second = _new(migrated_engine, turn="t1")

    assert [s.id for s in list_turn_suggestions(migrated_engine, "t1")] == [first.id, second.id]
    assert list_turn_suggestions(migrated_engine, "nope") == []


def test_count_open_by_target_stage_counts_only_open_ones_of_that_project(
    migrated_engine: Engine,
) -> None:
    a = _new(migrated_engine, to_stage="narrative")
    _new(migrated_engine, to_stage="narrative")
    _new(migrated_engine, to_stage="topic")
    _new(migrated_engine, project="other", to_stage="topic")
    resolve_suggestion(migrated_engine, a.id, "applied")

    assert count_open_by_target_stage(migrated_engine, "p") == {"narrative": 1, "topic": 1}
    assert count_open_by_target_stage(migrated_engine, "nothing") == {}
