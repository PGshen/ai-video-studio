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
    sections_for,
)
from studio.timeline.schema import LyricLine


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


# ---- 歌词意象（mv-lyrics design §4） ----------------------------------------------------------

LYRICS = [
    LyricLine(text="凌晨三点 机房亮着光", start=2.0, end=6.0),
    LyricLine(text="指数曲线 撞穿屋顶", start=6.0, end=10.0),
    LyricLine(text="啊", start=10.0, end=12.0),
]
IMAGERY = "歌词意象"


def _lyric_brief(
    imagery: str | None = "「凌晨三点 机房亮着光」→ 机架线框图，关键字「光」卡第一拍。",
) -> str:
    base = _brief()
    if imagery is None:
        return base
    section = f"## {IMAGERY}\n\n{imagery}\n"
    marker = "## 参考与灵感"
    return base.replace(marker, section + "\n" + marker, 1)


def test_sections_for_lyrics_put_the_imagery_after_the_visual_motif() -> None:
    assert sections_for(has_lyrics=False) == SECTIONS
    with_lyrics = sections_for(has_lyrics=True)
    assert len(with_lyrics) == 9
    assert with_lyrics.index(IMAGERY) == with_lyrics.index("视觉母题") + 1


def test_a_brief_with_a_quoted_lyric_passes_when_lyrics_exist() -> None:
    result = check_concept_text(_lyric_brief(), LYRICS)
    assert result.errors == [] and result.warnings == []
    assert result.found_sections == 9


def test_the_imagery_section_is_required_when_lyrics_exist() -> None:
    result = check_concept_text(_lyric_brief(None), LYRICS)
    assert "缺少章节「歌词意象」" in result.errors


def test_an_empty_imagery_section_is_an_error() -> None:
    result = check_concept_text(_lyric_brief(""), LYRICS)
    assert "章节「歌词意象」没有内容" in result.errors


def test_imagery_that_quotes_no_real_lyric_is_an_error_with_examples() -> None:
    result = check_concept_text(_lyric_brief("一个红色的圆点慢慢变大，然后爆炸。"), LYRICS)
    (error,) = [e for e in result.errors if "歌词意象" in e]
    assert "没有逐字引用" in error and "凌晨三点 机房亮着光" in error


@pytest.mark.parametrize(
    "quote",
    ["凌晨三点机房亮着光", "凌晨三点　机房亮着光", "「凌晨三点  机房亮着光」"],
)
def test_quotes_ignore_whitespace_differences(quote: str) -> None:
    assert check_concept_text(_lyric_brief(f"{quote} → 机架"), LYRICS).errors == []


@pytest.mark.parametrize(
    "quote",
    ["凌晨三点，机房亮着光", "凌晨三点,机房亮着光！", "「凌晨三点」「机房亮着光」"],
)
def test_quotes_ignore_punctuation_and_full_width_differences(quote: str) -> None:
    assert check_concept_text(_lyric_brief(f"{quote} → 机架"), LYRICS).errors == []


def test_quotes_ignore_case_and_width_for_latin_lyrics() -> None:
    lyrics = [LyricLine(text="Hello, World again", start=1.0, end=3.0)]
    brief = _lyric_brief("ＨＥＬＬＯ world AGAIN → 一个点")
    assert check_concept_text(brief, lyrics).errors == []


def test_a_short_phrase_inside_the_imagery_is_not_a_quote_when_longer_lines_exist() -> None:
    lyrics = [
        LyricLine(text="爱你", start=1.0, end=2.0),
        LyricLine(text="凌晨三点 机房亮着光", start=2.0, end=6.0),
    ]
    result = check_concept_text(_lyric_brief("表达爱你的心情，一个红点"), lyrics)
    assert any("没有逐字引用" in e for e in result.errors)


def test_a_single_character_line_does_not_count_as_a_quote_when_longer_lines_exist() -> None:
    result = check_concept_text(_lyric_brief("啊 → 一个点"), LYRICS)
    assert any("没有逐字引用" in e for e in result.errors)


def test_without_lyrics_the_eight_sections_are_enough() -> None:
    assert check_concept_text(_brief(), None).errors == []


def _write_lyrics(workdir: Path, text: str) -> None:
    (workdir / "music").mkdir(exist_ok=True)
    (workdir / "music" / "lyrics.lrc").write_text(text, encoding="utf-8")


def test_the_workspace_check_follows_the_lyrics_file(tmp_path: Path) -> None:
    _write(tmp_path, _lyric_brief(None))
    assert check_workspace(tmp_path).errors == []  # no lyrics file: eight sections
    _write_lyrics(tmp_path, "[00:02.00]凌晨三点 机房亮着光\n")
    assert "缺少章节「歌词意象」" in check_workspace(tmp_path).errors
    _write(tmp_path, _lyric_brief())
    assert check_workspace(tmp_path).errors == []


def test_a_broken_lyrics_file_is_an_error_naming_the_file(tmp_path: Path) -> None:
    _write(tmp_path, _lyric_brief())
    _write_lyrics(tmp_path, "没有时间戳")
    errors = check_workspace(tmp_path).errors
    assert any("music/lyrics.lrc" in e for e in errors)


def test_the_status_summary_counts_nine_sections_with_lyrics(tmp_path: Path) -> None:
    _write(tmp_path, _lyric_brief())
    _write_lyrics(tmp_path, "[00:02.00]凌晨三点 机房亮着光\n")
    summary = STAGE.status_summary(tmp_path)
    assert "9/9" in summary and "歌词 1 句" in summary
