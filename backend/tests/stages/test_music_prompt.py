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
