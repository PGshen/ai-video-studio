"""`stages.common.suggest_upstream_change`（设计 §5.3/§5.4；计划 T6；TD-32）。

`Engine` 通过 `ToolContext.engine`（TD-32）传入 handler，`suggest_upstream_change`
因此和 `validate_scenes`/`render_preview` 一样是模块级 `ToolSpec` 常量
（`SUGGEST_UPSTREAM_CHANGE_TOOL`），不再需要工厂函数或阶段实例化时单独注入。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from studio.agent.tools import ToolContext, invoke_tool
from studio.db.repo.suggestions import list_suggestions
from studio.stages.common import SUGGEST_UPSTREAM_CHANGE_TOOL


@pytest.fixture
def ctx(workdir: Path, migrated_engine: Engine) -> ToolContext:
    return ToolContext(
        project_id="proj-1",
        stage="animation",
        workdir=workdir,
        record_tool_write=lambda relpath, sha256: None,
        engine=migrated_engine,
        upstream_stages=("narrative",),
    )


async def test_calling_tool_creates_open_suggestion(
    migrated_engine: Engine, ctx: ToolContext
) -> None:
    result = await invoke_tool(
        SUGGEST_UPSTREAM_CHANGE_TOOL,
        ctx,
        {"to_stage": "narrative", "content": "s-hook 的旁白和画面对不上，建议改一下这句台词。"},
    )

    assert result.is_error is False
    suggestions = list_suggestions(migrated_engine, "proj-1")
    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.status == "open"
    assert suggestion.from_stage == "animation"
    assert suggestion.to_stage == "narrative"
    assert suggestion.content == "s-hook 的旁白和画面对不上，建议改一下这句台词。"


def test_tool_is_scoped_to_the_stages_that_have_an_upstream_to_suggest_to() -> None:
    assert SUGGEST_UPSTREAM_CHANGE_TOOL.stages == {
        "narrative",
        "music",
        "animation_html",
        "produce",
    }


async def test_invalid_args_do_not_write_a_suggestion(
    migrated_engine: Engine, ctx: ToolContext
) -> None:
    result = await invoke_tool(SUGGEST_UPSTREAM_CHANGE_TOOL, ctx, {"content": "缺了 to_stage"})

    assert result.is_error is True
    assert list_suggestions(migrated_engine, "proj-1") == []


async def test_missing_engine_in_context_is_a_tool_error(workdir: Path) -> None:
    ctx_without_engine = ToolContext(
        project_id="proj-1",
        stage="animation",
        workdir=workdir,
        record_tool_write=lambda relpath, sha256: None,
    )

    result = await invoke_tool(
        SUGGEST_UPSTREAM_CHANGE_TOOL,
        ctx_without_engine,
        {"to_stage": "narrative", "content": "x"},
    )

    assert result.is_error is True
