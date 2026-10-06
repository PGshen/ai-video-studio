"""`check_concept`：`concept/brief.md` 的结构检查（子项目 3 设计 §6.1）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.concept import STAGE
from studio.stages.concept.check_concept import (
    CHECK_CONCEPT_TOOL,
    SECTIONS,
    check_concept_text,
    check_workspace,
)


def _brief(**overrides: str) -> str:
    bodies = {name: f"{name}的内容。" for name in SECTIONS}
    bodies["目标时长"] = "30 秒"
    bodies.update(overrides)
    return "\n".join(f"## {name}\n\n{bodies[name]}\n" for name in SECTIONS)


def _ctx(workdir: Path) -> ToolContext:
    return ToolContext(
        project_id="p", stage="concept", workdir=workdir, record_tool_write=lambda *_: None
    )


def _write(workdir: Path, text: str) -> None:
    (workdir / "concept").mkdir(exist_ok=True)
    (workdir / "concept" / "brief.md").write_text(text, encoding="utf-8")


def test_sections_are_the_eight_from_the_design() -> None:
    assert SECTIONS == (
        "主题",
        "目标时长",
        "硬性要求",
        "情绪与能量走向",
        "视觉母题",
        "参考与灵感",
        "段落草图",
        "风险点",
    )


def test_a_complete_brief_passes_and_reports_the_target() -> None:
    result = check_concept_text(_brief())
    assert result.errors == [] and result.target_seconds == pytest.approx(30.0)


def test_empty_text_and_missing_sections_are_errors_listed_together() -> None:
    assert any("为空" in e for e in check_concept_text("").errors)
    result = check_concept_text("## 主题\n\n只有这一章\n")
    assert sum("缺少章节" in e for e in result.errors) == 7


def test_empty_section_is_an_error() -> None:
    result = check_concept_text(_brief(视觉母题="   "))
    assert any("视觉母题" in e and "没有内容" in e for e in result.errors)


@pytest.mark.parametrize("value", ["很短", "30", "一分钟"])
def test_unparseable_target_duration_is_an_error(value: str) -> None:
    result = check_concept_text(_brief(目标时长=value))
    assert any("目标时长" in e and "秒" in e for e in result.errors)
    assert result.target_seconds is None


def test_minutes_are_accepted_for_the_target() -> None:
    assert check_concept_text(_brief(目标时长="1 分钟")).target_seconds == pytest.approx(60.0)


def test_headings_inside_code_fences_do_not_count_and_numbering_is_tolerated() -> None:
    text = _brief().replace("## 主题", "## 1. 主题") + "\n```\n## 风险点\n```\n"
    assert check_concept_text(text).errors == []


def test_order_and_extra_sections_are_only_warnings() -> None:
    text = _brief() + "\n## 附录\n\n额外内容\n"
    result = check_concept_text(text)
    assert result.errors == [] and any("附录" in w for w in result.warnings)
    swapped = (
        _brief()
        .replace("## 主题", "## 临时")
        .replace("## 风险点", "## 主题")
        .replace("## 临时", "## 风险点")
    )
    assert any("顺序" in w for w in check_concept_text(swapped).warnings)


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    assert any("brief.md" in e for e in check_workspace(tmp_path).errors)


async def test_tool_reports_pass_errors_and_is_registered_for_concept_only(tmp_path: Path) -> None:
    assert CHECK_CONCEPT_TOOL.stages == {"concept"}
    assert {"check_concept", "web_search", "fetch_url", "analyze_music"} == {
        t.name for t in STAGE.tools()
    }
    _write(tmp_path, _brief())
    ok = await invoke_tool(CHECK_CONCEPT_TOOL, _ctx(tmp_path), {})
    assert not ok.is_error and "通过" in ok.text
    _write(tmp_path, "## 主题\n\nx\n")
    bad = await invoke_tool(CHECK_CONCEPT_TOOL, _ctx(tmp_path), {})
    assert bad.is_error and bad.text.count("缺少章节") == 7


def test_the_hard_requirements_section_is_required() -> None:
    without = "\n".join(
        f"## {name}\n\n{'30 秒' if name == '目标时长' else '内容。'}\n"
        for name in SECTIONS
        if name != "硬性要求"
    )
    result = check_concept_text(without)
    assert any("缺少章节「硬性要求」" in e for e in result.errors)


def test_an_empty_hard_requirements_section_is_an_error() -> None:
    result = check_concept_text(_brief(硬性要求="  "))
    assert any("「硬性要求」没有内容" in e for e in result.errors)


def test_the_hard_requirements_content_is_not_judged() -> None:
    assert check_concept_text(_brief(硬性要求="- 不要出现人脸\n- 总长不超过 40 秒")).errors == []
