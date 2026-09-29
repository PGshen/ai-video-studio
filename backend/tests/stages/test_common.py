"""`stages.common.suggest_upstream_change`（设计 §5.3/§5.4；计划 T6）。

`build_suggest_upstream_change_tool(engine)` 是一个工厂函数而不是模块级
`ToolSpec` 常量：`ToolSpec.handler` 要写 `suggestions` 表，需要一个
`Engine`，但 `StageDefinition.tools()` 目前是零参数方法（`agent/stage.py`），
调用链上（`TurnContext`/`ToolContext`）都没有线路能把 `Engine` 传到这一层
——加这条线路要改 `agent.tools.ToolContext`/`agent.runtime.TurnContext` 等
计划之外的公共接口，本任务不做（决策记录 D22）。这里直接测工厂函数本身
和 `invoke_tool` 的集成，不经过 `AnimationStage.tools()`。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from studio.agent.tools import ToolContext, invoke_tool
from studio.db.repo.suggestions import list_suggestions
from studio.stages.common import build_suggest_upstream_change_tool


@pytest.fixture
def ctx(workdir: Path) -> ToolContext:
    return ToolContext(
        project_id="proj-1",
        stage="animation",
        workdir=workdir,
        record_tool_write=lambda relpath, sha256: None,
    )


async def test_calling_tool_creates_open_suggestion(
    migrated_engine: Engine, ctx: ToolContext
) -> None:
    spec = build_suggest_upstream_change_tool(migrated_engine)

    result = await invoke_tool(
        spec,
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


async def test_tool_is_scoped_to_animation_stage(migrated_engine: Engine) -> None:
    spec = build_suggest_upstream_change_tool(migrated_engine)

    assert spec.stages == {"animation"}


async def test_invalid_args_do_not_write_a_suggestion(
    migrated_engine: Engine, ctx: ToolContext
) -> None:
    spec = build_suggest_upstream_change_tool(migrated_engine)

    result = await invoke_tool(spec, ctx, {"content": "缺了 to_stage"})

    assert result.is_error is True
    assert list_suggestions(migrated_engine, "proj-1") == []
