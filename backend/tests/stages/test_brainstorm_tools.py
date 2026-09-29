"""头脑风暴阶段的三个业务工具（设计 §5.0；计划 M4 T4）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from studio.agent.tools import ToolContext, ToolResult, ToolSpec, invoke_tool
from studio.db.repo.ideas import create_idea, get_idea, list_ideas, mark_picked, update_idea
from studio.stages.brainstorm import STAGE
from studio.stages.brainstorm.tools import (
    CREATE_IDEA_TOOL,
    LIST_IDEAS_TOOL,
    UPDATE_IDEA_TOOL,
)


@pytest.fixture
def ctx(workdir: Path, migrated_engine: Engine) -> ToolContext:
    return ToolContext(
        project_id=None,
        stage="brainstorm",
        workdir=workdir,
        record_tool_write=lambda *_: None,
        engine=migrated_engine,
        session_id="sess-1",
    )


async def _call(spec: ToolSpec, ctx: ToolContext, **args: object) -> ToolResult:
    return await invoke_tool(spec, ctx, dict(args))


def test_stage_exposes_idea_tools_and_web_tools() -> None:
    assert {t.name for t in STAGE.tools()} == {
        "list_ideas",
        "create_idea",
        "update_idea",
        "web_search",
        "fetch_url",
    }
    for tool in STAGE.tools():
        assert "brainstorm" in tool.stages


class TestCreateIdea:
    async def test_creates_card_with_source_session(
        self, ctx: ToolContext, migrated_engine: Engine
    ) -> None:
        result = await _call(
            CREATE_IDEA_TOOL,
            ctx,
            title="排序为什么快",
            pitch="十亿条记录一秒排完",
            counterintuitive="大家以为排序慢，其实分治让它很快",
            tags=["算法"],
            scores={"counterintuitive": 5, "visual": 4},
        )
        assert not result.is_error, result.text
        (idea,) = list_ideas(migrated_engine)
        assert idea.title == "排序为什么快"
        assert idea.source_session_id == "sess-1"
        assert idea.scores == {"counterintuitive": 5, "visual": 4}
        assert idea.id in result.text

    async def test_duplicate_title_reports_existing_card(
        self, ctx: ToolContext, migrated_engine: Engine
    ) -> None:
        first = create_idea(migrated_engine, title="Hello World")
        result = await _call(
            CREATE_IDEA_TOOL, ctx, title="hello  world", pitch="p", counterintuitive="c"
        )
        assert result.is_error
        assert first.id in result.text and "Hello World" in result.text
        assert len(list_ideas(migrated_engine, status="all")) == 1

    @pytest.mark.parametrize(
        "args",
        [
            {"title": "x", "pitch": "p", "counterintuitive": "c", "scores": {"novelty": 9}},
            {"title": "x", "pitch": "p", "counterintuitive": "c", "scores": {"boring": 3}},
            {
                "title": "x",
                "pitch": "p",
                "counterintuitive": "c",
                "tags": [f"t{i}" for i in range(9)],
            },
            {"title": "  ", "pitch": "p", "counterintuitive": "c"},
            {"title": "x", "pitch": "p"},  # missing counterintuitive
            {"title": "x", "pitch": "", "counterintuitive": "c"},
        ],
    )
    async def test_invalid_args_are_tool_errors(
        self, ctx: ToolContext, migrated_engine: Engine, args: dict[str, object]
    ) -> None:
        result = await _call(CREATE_IDEA_TOOL, ctx, **args)
        assert result.is_error
        assert list_ideas(migrated_engine, status="all") == []

    async def test_without_engine_is_internal_error(self, workdir: Path) -> None:
        no_engine = ToolContext(
            project_id=None, stage="brainstorm", workdir=workdir, record_tool_write=lambda *_: None
        )
        result = await _call(
            CREATE_IDEA_TOOL, no_engine, title="x", pitch="p", counterintuitive="c"
        )
        assert result.is_error and "数据库" in result.text


class TestListIdeas:
    async def test_lists_all_statuses_with_ids_and_status(
        self, ctx: ToolContext, migrated_engine: Engine
    ) -> None:
        a = create_idea(
            migrated_engine, title="A 想法", tags=["x"], scores={"novelty": 4, "visual": 2}
        )
        b = create_idea(migrated_engine, title="B 想法")
        update_idea(migrated_engine, b.id, status="archived")
        c = create_idea(migrated_engine, title="C 想法")
        mark_picked(migrated_engine, c.id, "p1")

        result = await _call(LIST_IDEAS_TOOL, ctx)

        assert not result.is_error
        for idea in (a, b, c):
            assert idea.id in result.text
        assert "archived" in result.text and "picked" in result.text
        assert "6" in result.text  # total score of A

    async def test_filters_by_status_and_query(
        self, ctx: ToolContext, migrated_engine: Engine
    ) -> None:
        a = create_idea(migrated_engine, title="排序算法", pitch="分治", tags=["算法"])
        b = create_idea(migrated_engine, title="黑洞", pitch="视界")
        update_idea(migrated_engine, b.id, status="archived")

        by_status = await _call(LIST_IDEAS_TOOL, ctx, status="archived")
        assert b.id in by_status.text and a.id not in by_status.text

        by_query = await _call(LIST_IDEAS_TOOL, ctx, query="分治")
        assert a.id in by_query.text and b.id not in by_query.text
        by_tag = await _call(LIST_IDEAS_TOOL, ctx, query="算法")
        assert a.id in by_tag.text

    async def test_empty_pool_says_so(self, ctx: ToolContext) -> None:
        result = await _call(LIST_IDEAS_TOOL, ctx)
        assert not result.is_error
        assert "还没有" in result.text

    async def test_caps_at_50_and_says_truncated(
        self, ctx: ToolContext, migrated_engine: Engine
    ) -> None:
        for i in range(55):
            create_idea(migrated_engine, title=f"想法 {i}")
        result = await _call(LIST_IDEAS_TOOL, ctx)
        assert result.text.count("想法 ") >= 50
        assert "共 55" in result.text and "只显示前 50" in result.text

    async def test_rejects_unknown_status(self, ctx: ToolContext) -> None:
        assert (await _call(LIST_IDEAS_TOOL, ctx, status="weird")).is_error


class TestUpdateIdea:
    async def test_updates_only_given_fields(
        self, ctx: ToolContext, migrated_engine: Engine
    ) -> None:
        idea = create_idea(
            migrated_engine, title="A", pitch="旧", tags=["x"], scores={"novelty": 3}
        )
        result = await _call(UPDATE_IDEA_TOOL, ctx, id=idea.id, pitch="新", scores={"visual": 5})
        assert not result.is_error, result.text
        updated = get_idea(migrated_engine, idea.id)
        assert updated is not None
        assert updated.pitch == "新" and updated.tags == ["x"]
        assert updated.scores == {"novelty": 3, "visual": 5}  # merged per dimension

    async def test_invalid_score_in_update_is_error_and_changes_nothing(
        self, ctx: ToolContext, migrated_engine: Engine
    ) -> None:
        idea = create_idea(migrated_engine, title="A", pitch="旧")
        result = await _call(UPDATE_IDEA_TOOL, ctx, id=idea.id, pitch="新", scores={"visual": 9})
        assert result.is_error
        unchanged = get_idea(migrated_engine, idea.id)
        assert unchanged is not None and unchanged.pitch == "旧"

    async def test_can_rename_with_duplicate_check(
        self, ctx: ToolContext, migrated_engine: Engine
    ) -> None:
        a = create_idea(migrated_engine, title="A")
        create_idea(migrated_engine, title="B")
        assert (await _call(UPDATE_IDEA_TOOL, ctx, id=a.id, title="b")).is_error
        assert not (await _call(UPDATE_IDEA_TOOL, ctx, id=a.id, title="A2")).is_error

    @pytest.mark.parametrize("status", ["picked", "archived"])
    async def test_refuses_cards_that_are_not_plain_ideas(
        self, ctx: ToolContext, migrated_engine: Engine, status: str
    ) -> None:
        idea = create_idea(migrated_engine, title="A")
        if status == "picked":
            mark_picked(migrated_engine, idea.id, "p")
        else:
            update_idea(migrated_engine, idea.id, status="archived")
        result = await _call(UPDATE_IDEA_TOOL, ctx, id=idea.id, pitch="改")
        assert result.is_error and status in result.text
        after = get_idea(migrated_engine, idea.id)
        assert after is not None and after.pitch is None

    async def test_unknown_id_and_no_changes_are_errors(
        self, ctx: ToolContext, migrated_engine: Engine
    ) -> None:
        assert (await _call(UPDATE_IDEA_TOOL, ctx, id="nope", pitch="x")).is_error
        idea = create_idea(migrated_engine, title="A")
        nothing = await _call(UPDATE_IDEA_TOOL, ctx, id=idea.id)
        assert nothing.is_error and "没有" in nothing.text

    async def test_tool_has_no_status_parameter(self) -> None:
        assert "status" not in UPDATE_IDEA_TOOL.input_model.model_fields
