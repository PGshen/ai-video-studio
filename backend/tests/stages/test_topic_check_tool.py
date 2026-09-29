"""`check_brief` 工具（计划 M4 T6）。"""

from __future__ import annotations

from pathlib import Path

from brief_builder import FIXTURE
from brief_builder import make_brief as _brief
from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.topic import STAGE
from studio.stages.topic.check_brief import CHECK_BRIEF_TOOL


def _ctx(workdir: Path) -> ToolContext:
    return ToolContext(
        project_id="p", stage="topic", workdir=workdir, record_tool_write=lambda *_: None
    )


def _write(workdir: Path, text: str) -> None:
    (workdir / "topic").mkdir(exist_ok=True)
    (workdir / "topic" / "brief.md").write_text(text, encoding="utf-8")


def test_tool_is_registered_for_topic_only() -> None:
    assert CHECK_BRIEF_TOOL.stages == {"topic"}
    assert {"check_brief", "web_search", "fetch_url"} == {t.name for t in STAGE.tools()}


async def test_passes(workdir: Path) -> None:
    _write(workdir, FIXTURE.read_text(encoding="utf-8"))
    result = await invoke_tool(CHECK_BRIEF_TOOL, _ctx(workdir), {})
    assert not result.is_error
    assert "通过" in result.text


async def test_errors_are_listed_all_at_once(workdir: Path) -> None:
    _write(workdir, "## 核心问题\n\n只有这一章\n")
    result = await invoke_tool(CHECK_BRIEF_TOOL, _ctx(workdir), {})
    assert result.is_error
    assert result.text.count("缺少章节") == 6


async def test_warnings_do_not_make_it_an_error(workdir: Path) -> None:
    _write(workdir, _brief(风险点="没有。"))
    result = await invoke_tool(CHECK_BRIEF_TOOL, _ctx(workdir), {})
    assert not result.is_error
    assert "警告" in result.text and "风险点" in result.text


async def test_missing_file_is_error(workdir: Path) -> None:
    result = await invoke_tool(CHECK_BRIEF_TOOL, _ctx(workdir), {})
    assert result.is_error and "brief.md" in result.text
