"""`stages.topic.brief`：选题简报的结构检查（设计 §5.1；计划 M4 T6）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from brief_builder import FIXTURE
from brief_builder import make_brief as _brief
from studio.stages.topic.brief import SECTIONS, check, check_workspace


def test_sections_match_design() -> None:
    assert SECTIONS == (
        "核心问题",
        "钩子与反直觉点",
        "目标观众与前置知识",
        "关键事实",
        "叙事角度与结构草图",
        "可视化机会",
        "风险点",
    )


def test_good_brief_passes_without_warnings() -> None:
    result = check(_brief())
    assert result.errors == [] and result.warnings == []
    assert result.ok


def test_fixture_brief_passes() -> None:
    result = check(FIXTURE.read_text(encoding="utf-8"))
    assert result.errors == [], result.errors


@pytest.mark.parametrize("text", [None, "", "  \n\n"])
def test_missing_or_empty_file(text: str | None) -> None:
    result = check(text)
    assert not result.ok
    assert any("brief.md" in e for e in result.errors)


def test_missing_section_is_named() -> None:
    result = check(_brief(风险点=None))
    assert any("缺少章节「风险点」" in e for e in result.errors)


def test_all_missing_sections_are_reported_at_once() -> None:
    result = check("# 只有标题\n\n## 核心问题\n\n有内容\n")
    missing = [e for e in result.errors if e.startswith("缺少章节")]
    assert len(missing) == 6


def test_empty_section_is_error() -> None:
    result = check(_brief(可视化机会="   "))
    assert any("章节「可视化机会」是空的" in e for e in result.errors)


def test_facts_without_list_items_is_error() -> None:
    result = check(_brief(关键事实="归并排序是 O(n log n)，把握程度：高"))
    assert any("关键事实" in e and "列表项" in e for e in result.errors)


def test_fact_missing_source_is_named_with_index_and_excerpt() -> None:
    facts = (
        "- 第一条没问题（出处：教科书；把握程度：高）\n"
        "- 第二条完全没有出处也没有把握程度，写得很长很长很长很长很长"
    )
    result = check(_brief(关键事实=facts))
    joined = "\n".join(result.errors)
    assert "第 2 条" in joined and "第二条完全没有出处也没有把握" in joined
    assert "出处" in joined and "把握程度" in joined
    assert "第 1 条" not in joined


def test_fact_with_source_but_no_confidence() -> None:
    result = check(_brief(关键事实="- 某事实（出处：https://example.com/a）"))
    assert any("把握程度" in e for e in result.errors)
    assert not any("缺少出处" in e for e in result.errors)


@pytest.mark.parametrize("value", ["很高", "high", "大概", ""])
def test_fact_with_invalid_confidence(value: str) -> None:
    result = check(_brief(关键事实=f"- 某事实（出处：教科书；把握程度：{value}）"))
    assert any("把握程度" in e and "高/中/低" in e for e in result.errors)


def test_fact_with_empty_source_value() -> None:
    result = check(_brief(关键事实="- 某事实（出处：；把握程度：高）"))
    assert any("出处" in e for e in result.errors)


@pytest.mark.parametrize(
    "fact",
    [
        "- 某事实（出处：https://example.com/a?x=1,2；把握程度：中）",
        "- 某事实(出处:https://example.com/a;把握程度:中)",
        "* 某事实（出处：教科书，第 3 章；把握程度：高，可靠）",
        "1. 某事实（出处：论文 A；把握程度：低）",
        "- 某事实\n  （出处：https://example.com/a；把握程度：高）",  # continuation line
    ],
)
def test_fact_format_variants_are_accepted(fact: str) -> None:
    result = check(_brief(关键事实=fact))
    assert result.errors == [], result.errors


def test_low_confidence_facts_only_warn() -> None:
    facts = (
        "- A（出处：x；把握程度：低）\n- B（出处：y；把握程度：低）\n- C（出处：z；把握程度：高）"
    )
    result = check(_brief(关键事实=facts))
    assert result.ok
    assert any("2 条" in w and "低" in w for w in result.warnings)


def test_section_order_mismatch_only_warns() -> None:
    text = _brief()
    swapped = (
        text.replace("## 核心问题", "## TMP")
        .replace("## 风险点", "## 核心问题")
        .replace("## TMP", "## 风险点")
    )
    result = check(swapped)
    assert result.ok
    assert any("顺序" in w for w in result.warnings)


def test_unknown_h2_only_warns() -> None:
    result = check(_brief() + "\n## 附录\n\n随便写点。\n")
    assert result.ok
    assert any("附录" in w for w in result.warnings)


def test_short_risk_section_only_warns() -> None:
    result = check(_brief(风险点="没有。"))
    assert result.ok
    assert any("风险点" in w for w in result.warnings)


def test_numbered_headings_and_code_fences_are_handled() -> None:
    text = _brief().replace("## 核心问题", "## 1. 核心问题").replace("## 风险点", "## 七、风险点")
    text += "\n```\n## 这不是章节\n```\n"
    result = check(text)
    assert result.errors == [], result.errors
    assert not any("这不是章节" in w for w in result.warnings)


class TestCheckWorkspace:
    def test_missing_file(self, tmp_path: Path) -> None:
        result = check_workspace(tmp_path)
        assert not result.ok and any("brief.md" in e for e in result.errors)

    def test_reads_topic_brief(self, tmp_path: Path) -> None:
        (tmp_path / "topic").mkdir()
        (tmp_path / "topic" / "brief.md").write_text(_brief(), encoding="utf-8")
        assert check_workspace(tmp_path).ok

    def test_non_utf8_is_error_not_exception(self, tmp_path: Path) -> None:
        (tmp_path / "topic").mkdir()
        (tmp_path / "topic" / "brief.md").write_bytes(b"\xff\xfe\x00bad")
        result = check_workspace(tmp_path)
        assert not result.ok and any("UTF-8" in e for e in result.errors)
