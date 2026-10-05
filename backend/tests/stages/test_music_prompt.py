"""`music` 阶段提示词：契约与要领都在（子项目 3 设计 §7.5）。"""

from __future__ import annotations

import pytest

from studio.stages.music import STAGE

PROMPT = STAGE.system_prompt()


@pytest.mark.parametrize(
    "needle",
    [
        "music/compose.py",
        "STUDIO_TIMELINE",
        "STUDIO_OUT_WAV",
        "STUDIO_OUT_EVENTS",
        "render_music",
        "NumPy",
        "onset",
        "sweep",
        "upstream/timeline.json",
        "upstream/exemplar/audio-techniques.py",
    ],
)
def test_contract_terms_are_present(needle: str) -> None:
    assert needle in PROMPT


def test_prompt_is_honest_about_what_the_metrics_prove() -> None:
    assert "听不到" in PROMPT
    assert "指标只证明对齐" in PROMPT or "指标只能证明对齐" in PROMPT
    assert "无法验证" in PROMPT


def test_prompt_covers_both_arrangements_and_the_retime_rule() -> None:
    assert "短片" in PROMPT and "背景乐" in PROMPT
    assert "不许写死" in PROMPT or "不能写死" in PROMPT
    assert "淡出" in PROMPT  # smooth tails: a hard cut reads as a second onset
    for name in ("kick", "clap", "hat", "impact", "riser"):
        assert name in PROMPT


def test_prompt_first_decides_the_form() -> None:
    assert "先判断形态" in PROMPT
    assert "music/source.*" in PROMPT
    # the decision comes before either form's chapter
    assert PROMPT.index("先判断形态") < PROMPT.index("导入形态")


@pytest.mark.parametrize(
    "needle",
    [
        "analyze_music",
        "validate_sections",
        "music/sections.json",
        "强拍",
        "range",
        "offset",
        "置信度",
        "残差",
    ],
)
def test_import_chapter_covers_the_workflow(needle: str) -> None:
    chapter = PROMPT[PROMPT.index("# 导入形态") :]
    assert needle in chapter


def test_import_chapter_is_honest_about_listening_and_derived_data() -> None:
    chapter = PROMPT[PROMPT.index("# 导入形态") :]
    assert "听不到" in chapter
    assert "音色" in chapter and "情绪" in chapter
    assert "能量曲线" in chapter
    assert "不要改" in chapter and "analysis.json" in chapter
    assert "如实告诉用户" in chapter or "如实转告用户" in chapter
    assert "用户确认" in chapter
