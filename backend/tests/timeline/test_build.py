"""`studio.timeline.build`：旁白层构建、文档合并、哈希（设计 §4.2）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from studio.timeline.build import (
    LayerNotSupported,
    NarrationInput,
    TimelineError,
    TimelineLayers,
    build_timeline,
    narration_from_documents,
    timeline_hash,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "animation"


def _docs() -> tuple[dict[str, Any], dict[str, Any]]:
    narrative = json.loads((FIXTURES / "narrative.json").read_text(encoding="utf-8"))
    timing = json.loads((FIXTURES / "timing.json").read_text(encoding="utf-8"))
    return narrative, timing


def _two_scenes() -> list[NarrationInput]:
    return [
        NarrationInput("s-a", "甲", 2.0, [(0.0, 1.0, "一"), (1.0, 2.0, "二")]),
        NarrationInput("s-b", "乙", 3.0, [(0.5, 2.5, "三")]),
    ]


def test_build_accumulates_section_starts_and_globalises_beats() -> None:
    tl = build_timeline(TimelineLayers(narration=_two_scenes()))
    assert tl.duration == pytest.approx(5.0)
    assert [(s.id, s.start, s.end) for s in tl.sections] == [("s-a", 0.0, 2.0), ("s-b", 2.0, 5.0)]
    assert tl.sections[1].label == "乙"
    beat = tl.narration[1].beats[0]
    assert (beat.start, beat.end, beat.cue_text) == (2.5, 4.5, "三")
    assert tl.grid is None and tl.music is None


@pytest.mark.parametrize("layer", ["grid", "moments", "music"])
def test_reserved_layers_are_rejected(layer: str) -> None:
    layers = TimelineLayers(narration=_two_scenes(), **{layer: {"anything": 1}})
    with pytest.raises(LayerNotSupported):
        build_timeline(layers)


def test_empty_narration_is_an_error() -> None:
    with pytest.raises(TimelineError):
        build_timeline(TimelineLayers(narration=[]))


def test_documents_merge_fixture_with_hyphenated_scene_ids() -> None:
    narrative, timing = _docs()
    scenes = narration_from_documents(narrative, timing)
    assert [s.scene_id for s in scenes] == ["s-hook", "s-explain"]
    assert scenes[0].duration_seconds == 1.4
    assert scenes[0].beats[0] == (0.0, 0.7, "如果一个排序算法能在一秒内处理十亿条记录")
    assert scenes[0].label == "用一个不断增长的数字条引出问题，制造悬念"
    tl = build_timeline(TimelineLayers(narration=scenes))
    assert tl.sections[1].start == pytest.approx(1.4)


def test_label_falls_back_to_scene_id_without_visual_intent() -> None:
    narrative, timing = _docs()
    narrative["scenes"][0]["visual_intent"] = ""
    assert narration_from_documents(narrative, timing)[0].label == "s-hook"


def _errors(narrative: dict[str, Any], timing: dict[str, Any]) -> tuple[str, ...]:
    with pytest.raises(TimelineError) as exc:
        narration_from_documents(narrative, timing)
    return exc.value.errors


def test_missing_timing_record() -> None:
    narrative, timing = _docs()
    timing["scenes"].pop()
    errors = _errors(narrative, timing)
    assert any("s-explain" in e and "timing" in e for e in errors)


def test_beat_count_mismatch() -> None:
    narrative, timing = _docs()
    timing["scenes"][0]["beats"].pop()
    assert any("s-hook" in e and "beat 数" in e for e in _errors(narrative, timing))


def test_beat_inverted_and_out_of_range_reported_together() -> None:
    narrative, timing = _docs()
    timing["scenes"][0]["beats"][0] = {"start_seconds": 0.6, "end_seconds": 0.2}
    timing["scenes"][1]["beats"][1] = {"start_seconds": 0.8, "end_seconds": 1.7}
    errors = _errors(narrative, timing)
    assert any("s-hook" in e and "倒置" in e for e in errors)
    assert any("s-explain" in e and "超出" in e for e in errors)


def test_beat_overrun_within_tolerance_is_accepted() -> None:
    narrative, timing = _docs()
    timing["scenes"][1]["beats"][1] = {"start_seconds": 0.8, "end_seconds": 1.64}
    assert narration_from_documents(narrative, timing)


def test_non_positive_duration_and_duplicate_ids() -> None:
    narrative, timing = _docs()
    timing["scenes"][0]["duration_seconds"] = 0
    narrative["scenes"][1]["id"] = "s-hook"
    errors = _errors(narrative, timing)
    assert any("时长" in e for e in errors)
    assert any("重复" in e for e in errors)


def test_no_scenes_is_an_error() -> None:
    assert _errors({"scenes": []}, {"scenes": []})


def test_hash_is_stable_sensitive_and_key_order_independent() -> None:
    a = build_timeline(TimelineLayers(narration=_two_scenes()))
    b = build_timeline(TimelineLayers(narration=_two_scenes()))
    assert timeline_hash(a) == timeline_hash(b)
    assert len(timeline_hash(a)) == 64
    changed = _two_scenes()
    changed[1] = NarrationInput("s-b", "乙", 3.0, [(0.6, 2.5, "三")])
    assert timeline_hash(build_timeline(TimelineLayers(narration=changed))) != timeline_hash(a)


@pytest.mark.parametrize("bad_id", ["开场", "s two", "../x", "a/b", "a.b", ""])
def test_scene_ids_are_restricted_to_a_safe_character_set(bad_id: str) -> None:
    narrative, timing = _docs()
    narrative["scenes"][0]["id"] = bad_id
    timing["scenes"][0]["id"] = bad_id
    errors = _errors(narrative, timing)
    assert any("镜头 id" in e for e in errors)
