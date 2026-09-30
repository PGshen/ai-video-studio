"""`suggest_upstream_change` 的校验（计划 M5 T9，决策 D4）：只能向**直接上游**提，内容非空且有上限，
记录产生它的 turn。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from studio.agent.tools import ToolContext, ToolResult, invoke_tool
from studio.db.repo.suggestions import list_suggestions
from studio.stages.common import SUGGEST_UPSTREAM_CHANGE_TOOL
from studio.stages.common.suggest_upstream_change import MAX_CONTENT_CHARS


def _ctx(
    workdir: Path,
    engine: Engine,
    *,
    stage: str = "animation",
    upstream: tuple[str, ...] = ("narrative",),
    turn_id: str | None = "turn-1",
) -> ToolContext:
    return ToolContext(
        project_id="proj-1",
        stage=stage,
        workdir=workdir,
        record_tool_write=lambda relpath, sha256: None,
        engine=engine,
        turn_id=turn_id,
        upstream_stages=upstream,
    )


async def _call(ctx: ToolContext, **args: object) -> ToolResult:
    return await invoke_tool(SUGGEST_UPSTREAM_CHANGE_TOOL, ctx, dict(args))


async def test_animation_can_suggest_to_narrative(workdir: Path, migrated_engine: Engine) -> None:
    result = await _call(
        _ctx(workdir, migrated_engine), to_stage="narrative", content="s-hook 的旁白太长"
    )

    assert result.is_error is False
    [suggestion] = list_suggestions(migrated_engine, "proj-1")
    assert (suggestion.from_stage, suggestion.to_stage) == ("animation", "narrative")


async def test_narrative_can_suggest_to_topic(workdir: Path, migrated_engine: Engine) -> None:
    ctx = _ctx(workdir, migrated_engine, stage="narrative", upstream=("topic",))

    result = await _call(ctx, to_stage="topic", content="简报里的第二条事实和出处对不上")

    assert result.is_error is False
    [suggestion] = list_suggestions(migrated_engine, "proj-1")
    assert (suggestion.from_stage, suggestion.to_stage) == ("narrative", "topic")


@pytest.mark.parametrize(
    "to_stage", ["topic", "animation", "brainstorm", "publish", "", "Narrative", "narrative,topic"]
)
async def test_anything_but_the_direct_upstream_is_rejected_with_the_valid_choice(
    workdir: Path, migrated_engine: Engine, to_stage: str
) -> None:
    result = await _call(_ctx(workdir, migrated_engine), to_stage=to_stage, content="有问题")

    assert result.is_error is True
    assert "narrative" in result.text  # 告诉 agent 该填什么
    assert list_suggestions(migrated_engine, "proj-1") == []


async def test_a_stage_without_upstream_gets_a_clear_error(
    workdir: Path, migrated_engine: Engine
) -> None:
    ctx = _ctx(workdir, migrated_engine, stage="topic", upstream=())

    result = await _call(ctx, to_stage="narrative", content="有问题")

    assert result.is_error is True
    assert "没有上游" in result.text
    assert list_suggestions(migrated_engine, "proj-1") == []


async def test_surrounding_whitespace_in_to_stage_is_tolerated(
    workdir: Path, migrated_engine: Engine
) -> None:
    result = await _call(_ctx(workdir, migrated_engine), to_stage=" narrative\n", content="x")

    assert result.is_error is False
    assert list_suggestions(migrated_engine, "proj-1")[0].to_stage == "narrative"


@pytest.mark.parametrize("content", ["", "   ", "\n\t\n"])
async def test_blank_content_is_rejected(
    workdir: Path, migrated_engine: Engine, content: str
) -> None:
    result = await _call(_ctx(workdir, migrated_engine), to_stage="narrative", content=content)

    assert result.is_error is True
    assert "内容" in result.text
    assert list_suggestions(migrated_engine, "proj-1") == []


async def test_content_is_stored_stripped(workdir: Path, migrated_engine: Engine) -> None:
    await _call(_ctx(workdir, migrated_engine), to_stage="narrative", content="  改这里  \n")

    assert list_suggestions(migrated_engine, "proj-1")[0].content == "改这里"


async def test_content_length_limit_is_inclusive(workdir: Path, migrated_engine: Engine) -> None:
    ctx = _ctx(workdir, migrated_engine)

    ok = await _call(ctx, to_stage="narrative", content="字" * MAX_CONTENT_CHARS)
    too_long = await _call(ctx, to_stage="narrative", content="字" * (MAX_CONTENT_CHARS + 1))

    assert ok.is_error is False
    assert too_long.is_error is True
    assert str(MAX_CONTENT_CHARS) in too_long.text
    assert len(list_suggestions(migrated_engine, "proj-1")) == 1


async def test_the_producing_turn_is_recorded(workdir: Path, migrated_engine: Engine) -> None:
    await _call(
        _ctx(workdir, migrated_engine, turn_id="turn-42"), to_stage="narrative", content="x"
    )

    assert list_suggestions(migrated_engine, "proj-1")[0].turn_id == "turn-42"


def test_max_content_length_is_2000() -> None:
    assert MAX_CONTENT_CHARS == 2000
