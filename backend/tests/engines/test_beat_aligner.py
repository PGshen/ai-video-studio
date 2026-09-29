"""`engines.tts.beat_aligner`/`text_normalize` 测试（计划 M3 T2）。"""

from __future__ import annotations

import pytest

from studio.engines.tts.beat_aligner import align_scene_beats
from studio.engines.tts.text_normalize import normalize_alignment_text


def test_normalize_strips_whitespace_and_maps_fullwidth_punctuation() -> None:
    assert normalize_alignment_text("你好，世界！ 空格\n继续") == "你好,世界!空格继续"


def test_align_full_coverage_produces_monotonic_and_aligned_beats() -> None:
    scene = {
        "narration": "如果一个排序算法能在一秒内处理十亿条记录你会好奇它到底做了什么",
        "duration_seconds": 1.4,
        "beats": [
            {"cue_text": "如果一个排序算法能在一秒内处理十亿条记录"},
            {"cue_text": "你会好奇它到底做了什么"},
        ],
        "word_timestamps": [
            {
                "word": "如果一个排序算法能在一秒内处理十亿条记录",
                "start_time": 0.0,
                "end_time": 0.7,
            },
            {"word": "你会好奇它到底做了什么", "start_time": 0.7, "end_time": 1.4},
        ],
    }

    result = align_scene_beats(scene)

    beats = result["beats"]
    assert beats[0]["alignment_status"] == "aligned"
    assert beats[1]["alignment_status"] == "aligned"
    assert beats[0]["speech_start_seconds"] == 0.0
    assert beats[0]["speech_end_seconds"] == 0.7
    assert beats[1]["speech_start_seconds"] == 0.7
    assert beats[1]["speech_end_seconds"] == 1.4
    assert beats[0]["speech_end_seconds"] <= beats[1]["speech_start_seconds"]
    assert result["alignment_coverage"] == 1.0


def test_align_without_word_timestamps_interpolates_with_equal_weight() -> None:
    scene = {
        "narration": "甲乙丙丁",
        "duration_seconds": 2.0,
        "beats": [{"cue_text": "甲乙"}, {"cue_text": "丙丁"}],
        "word_timestamps": [],
    }

    result = align_scene_beats(scene)

    beats = result["beats"]
    assert beats[0]["alignment_status"] == "interpolated"
    assert beats[1]["alignment_status"] == "interpolated"
    # 等权重插值：两个 beat 平分 0~2.0s 的间隙。
    assert beats[0]["speech_start_seconds"] == 0.0
    assert beats[0]["speech_end_seconds"] == pytest.approx(1.0)
    assert beats[1]["speech_start_seconds"] == pytest.approx(1.0)
    assert beats[1]["speech_end_seconds"] == 2.0
    assert result["alignment_coverage"] == 0.0


def test_align_missing_duration_marks_failed_with_zero_coverage() -> None:
    scene = {
        "narration": "甲乙",
        "duration_seconds": None,
        "beats": [{"cue_text": "甲乙"}],
        "word_timestamps": [],
    }

    result = align_scene_beats(scene)

    assert result["beats"][0]["alignment_status"] == "failed"
    assert result["alignment_coverage"] == 0.0


def test_align_empty_beats_raises() -> None:
    with pytest.raises(ValueError):
        align_scene_beats(
            {"narration": "x", "duration_seconds": 1.0, "beats": [], "word_timestamps": []}
        )


def test_align_cue_text_mismatch_raises() -> None:
    scene = {
        "narration": "甲乙丙丁",
        "duration_seconds": 1.0,
        "beats": [{"cue_text": "甲乙"}, {"cue_text": "戊己"}],
        "word_timestamps": [],
    }
    with pytest.raises(ValueError):
        align_scene_beats(scene)
