"""`ideas` 仓储测试（计划 M4 T2）。"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from studio.db.repo.ideas import (
    DuplicateIdeaError,
    IdeaNotFoundError,
    IdeaStateError,
    IdeaValidationError,
    clean_scores,
    clean_tags,
    create_idea,
    find_duplicate,
    get_idea,
    list_ideas,
    mark_picked,
    normalize_title,
    update_idea,
)


def test_create_idea_defaults(migrated_engine: Engine) -> None:
    idea = create_idea(migrated_engine, title="  排序为什么这么快  ")
    assert idea.title == "排序为什么这么快"
    assert idea.status == "idea"
    assert idea.project_id is None
    assert idea.source_session_id is None
    assert idea.tags == []
    assert idea.scores == {}
    fetched = get_idea(migrated_engine, idea.id)
    assert fetched is not None
    assert (fetched.id, fetched.title, fetched.status) == (idea.id, idea.title, idea.status)


def test_create_idea_stores_all_fields(migrated_engine: Engine) -> None:
    idea = create_idea(
        migrated_engine,
        title="T",
        pitch="一句话",
        counterintuitive="大家以为 X，其实 Y",
        tags=["算法", "排序"],
        scores={"counterintuitive": 5, "visual": 3},
        source_session_id="s1",
    )
    assert idea.pitch == "一句话"
    assert idea.counterintuitive == "大家以为 X，其实 Y"
    assert idea.tags == ["算法", "排序"]
    assert idea.scores == {"counterintuitive": 5, "visual": 3}
    assert idea.source_session_id == "s1"


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_create_idea_rejects_bad_title(migrated_engine: Engine, title: str) -> None:
    with pytest.raises(IdeaValidationError):
        create_idea(migrated_engine, title=title)


@pytest.mark.parametrize(
    "variant", ["Hello  World", "hello world", " HELLO WORLD ", "Ｈｅｌｌｏ Ｗｏｒｌｄ"]
)
def test_duplicate_titles_are_detected_after_normalization(
    migrated_engine: Engine, variant: str
) -> None:
    first = create_idea(migrated_engine, title="Hello World")
    with pytest.raises(DuplicateIdeaError) as info:
        create_idea(migrated_engine, title=variant)
    assert info.value.existing.id == first.id
    found = find_duplicate(migrated_engine, variant)
    assert found is not None
    assert found.id == first.id


def test_duplicate_check_includes_archived_ideas(migrated_engine: Engine) -> None:
    first = create_idea(migrated_engine, title="旧想法")
    update_idea(migrated_engine, first.id, status="archived")
    with pytest.raises(DuplicateIdeaError):
        create_idea(migrated_engine, title="旧想法")


def test_normalize_title() -> None:
    assert normalize_title("  Ａ  b\n c ") == "a b c"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, {}),
        ({}, {}),
        ({"novelty": 4}, {"novelty": 4}),
        ({"visual": 4.0}, {"visual": 4}),
    ],
)
def test_clean_scores_accepts(raw: object, expected: dict[str, int]) -> None:
    assert clean_scores(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        {"boring": 3},
        {"novelty": 0},
        {"novelty": 6},
        {"novelty": 3.5},
        {"novelty": "4"},
        {"novelty": True},
        [1, 2],
    ],
)
def test_clean_scores_rejects(raw: object) -> None:
    with pytest.raises(IdeaValidationError):
        clean_scores(raw)


def test_clean_tags_strips_dedupes_and_limits() -> None:
    assert clean_tags([" 算法 ", "算法", "", "排序"]) == ["算法", "排序"]
    assert clean_tags(None) == []
    with pytest.raises(IdeaValidationError):
        clean_tags([f"t{i}" for i in range(9)])
    with pytest.raises(IdeaValidationError):
        clean_tags("算法")
    with pytest.raises(IdeaValidationError):
        clean_tags([1, 2])


def test_list_ideas_filters_by_status_newest_first(migrated_engine: Engine) -> None:
    a = create_idea(migrated_engine, title="A")
    b = create_idea(migrated_engine, title="B")
    c = create_idea(migrated_engine, title="C")
    update_idea(migrated_engine, c.id, status="archived")
    mark_picked(migrated_engine, b.id, "p1")

    assert [i.id for i in list_ideas(migrated_engine)] == [b.id, a.id]
    assert [i.id for i in list_ideas(migrated_engine, status="archived")] == [c.id]
    assert [i.id for i in list_ideas(migrated_engine, status="picked")] == [b.id]
    assert [i.id for i in list_ideas(migrated_engine, status="all")] == [c.id, b.id, a.id]


def test_update_idea_changes_only_given_fields(migrated_engine: Engine) -> None:
    idea = create_idea(migrated_engine, title="A", pitch="p", tags=["x"])
    updated = update_idea(migrated_engine, idea.id, pitch="新的", scores={"novelty": 2})
    assert updated.pitch == "新的"
    assert updated.tags == ["x"]
    assert updated.scores == {"novelty": 2}
    assert updated.title == "A"


def test_update_idea_can_clear_optional_text(migrated_engine: Engine) -> None:
    idea = create_idea(migrated_engine, title="A", pitch="p")
    assert update_idea(migrated_engine, idea.id, pitch=None).pitch is None


def test_update_idea_rename_checks_duplicates_but_not_itself(migrated_engine: Engine) -> None:
    a = create_idea(migrated_engine, title="A")
    create_idea(migrated_engine, title="B")
    with pytest.raises(DuplicateIdeaError):
        update_idea(migrated_engine, a.id, title="b")
    assert update_idea(migrated_engine, a.id, title="a").title == "a"


def test_update_idea_status_archive_and_restore(migrated_engine: Engine) -> None:
    idea = create_idea(migrated_engine, title="A")
    assert update_idea(migrated_engine, idea.id, status="archived").status == "archived"
    assert update_idea(migrated_engine, idea.id, status="idea").status == "idea"


def test_update_idea_rejects_setting_status_picked(migrated_engine: Engine) -> None:
    idea = create_idea(migrated_engine, title="A")
    with pytest.raises(IdeaValidationError):
        update_idea(migrated_engine, idea.id, status="picked")


def test_update_idea_missing_raises(migrated_engine: Engine) -> None:
    with pytest.raises(IdeaNotFoundError):
        update_idea(migrated_engine, "nope", pitch="x")


def test_mark_picked_sets_project_and_status(migrated_engine: Engine) -> None:
    idea = create_idea(migrated_engine, title="A")
    picked = mark_picked(migrated_engine, idea.id, "proj-1")
    assert picked.status == "picked"
    assert picked.project_id == "proj-1"


def test_mark_picked_twice_fails(migrated_engine: Engine) -> None:
    idea = create_idea(migrated_engine, title="A")
    mark_picked(migrated_engine, idea.id, "proj-1")
    with pytest.raises(IdeaStateError):
        mark_picked(migrated_engine, idea.id, "proj-2")
    fetched = get_idea(migrated_engine, idea.id)
    assert fetched is not None
    assert fetched.project_id == "proj-1"


def test_mark_picked_archived_or_missing_fails(migrated_engine: Engine) -> None:
    idea = create_idea(migrated_engine, title="A")
    update_idea(migrated_engine, idea.id, status="archived")
    with pytest.raises(IdeaStateError):
        mark_picked(migrated_engine, idea.id, "p")
    with pytest.raises(IdeaNotFoundError):
        mark_picked(migrated_engine, "nope", "p")


def test_picked_idea_cannot_be_archived_or_renamed(migrated_engine: Engine) -> None:
    idea = create_idea(migrated_engine, title="A")
    mark_picked(migrated_engine, idea.id, "p")
    with pytest.raises(IdeaStateError):
        update_idea(migrated_engine, idea.id, status="archived")
    with pytest.raises(IdeaStateError):
        update_idea(migrated_engine, idea.id, title="改名")
    assert update_idea(migrated_engine, idea.id, pitch="仍可改卖点").pitch == "仍可改卖点"
