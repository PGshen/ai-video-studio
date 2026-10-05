"""`engines.audio.analysis`：对齐类与观感类指标、能量曲线、事件校验（子项目 3 设计 §7.3）。"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures.audio_engine import SR, kick_events, kick_train, reel_timeline
from studio.engines.audio.analysis import analyze, validate_events
from studio.engines.audio.wav import Samples

BPM = 128.0


def _samples(data: np.ndarray, sr: int = SR) -> Samples:
    return Samples(data=data, sample_rate=sr)


def test_aligned_kick_train_has_high_alignment_and_matches() -> None:
    timeline = reel_timeline(BPM, 4)
    report = analyze(_samples(kick_train(BPM, 4)), timeline, kick_events(BPM, 4))
    assert report.duration == pytest.approx(timeline["duration"], abs=0.01)
    assert report.grid_alignment is not None and report.grid_alignment > 0.9
    kick = next(m for m in report.event_matches if m.name == "kick")
    assert kick.detectable >= 14 and kick.matched / kick.detectable > 0.9


def test_late_kicks_lower_the_grid_alignment_and_the_match_rate() -> None:
    timeline = reel_timeline(BPM, 4)
    report = analyze(_samples(kick_train(BPM, 4, shift=0.08)), timeline, kick_events(BPM, 4))
    assert report.grid_alignment is not None and report.grid_alignment < 0.3
    kick = next(m for m in report.event_matches if m.name == "kick")
    assert kick.matched / kick.detectable < 0.3
    assert report.unmatched and report.unmatched[0]["name"] == "kick"


def test_events_at_time_zero_and_overlapping_events_are_undetectable_not_failures() -> None:
    timeline = reel_timeline(BPM, 2)
    events = kick_events(BPM, 2) + [
        {"name": "hat", "kind": "onset", "start": 60 / BPM + 0.01, "end": 60 / BPM + 0.05},
        {"name": "riser", "kind": "sweep", "start": 0.5, "end": 1.5},
    ]
    report = analyze(_samples(kick_train(BPM, 2)), timeline, events)
    reasons = {(u["name"], u["start"] == 0.0) for u in report.undetectable}
    assert ("kick", True) in reasons
    assert any(u["name"] == "hat" for u in report.undetectable)
    assert all(m.name != "riser" for m in report.event_matches)  # sweeps are never scored


def test_peak_clipping_and_level_warnings() -> None:
    timeline = reel_timeline(BPM, 2)
    loud = np.clip(kick_train(BPM, 2) * 3.0, -1.0, 1.0)
    report = analyze(_samples(loud), timeline, [])
    assert report.clipped_samples > 0
    assert any("削波" in w for w in report.warnings)
    quiet = analyze(_samples(kick_train(BPM, 2) * 0.05), timeline, [])
    assert any("过轻" in w or "偏轻" in w for w in quiet.warnings)


def test_overall_level_targets_differ_for_reel_and_narration_bed() -> None:
    reel = reel_timeline(BPM, 2)
    bed = {
        **reel,
        "narration": [{"scene_id": "s1", "start": 0, "end": reel["duration"], "beats": []}],
    }
    medium = kick_train(BPM, 2) * 0.9
    reel_report = analyze(_samples(medium), reel, [])
    bed_report = analyze(_samples(medium), bed, [])
    assert not any("整体 RMS" in w for w in reel_report.warnings) or any(
        "整体 RMS" in w for w in bed_report.warnings
    )
    assert any("整体 RMS" in w and "背景乐" in w for w in bed_report.warnings)


def test_silence_does_not_crash_and_is_reported() -> None:
    timeline = reel_timeline(BPM, 2)
    report = analyze(_samples(np.zeros(int(timeline["duration"] * SR))), timeline, [])
    assert report.onsets == []
    assert report.grid_alignment is None
    assert any("静音" in w or "过轻" in w for w in report.warnings)


def test_energy_curve_maps_dbfs_to_unit_range() -> None:
    timeline = reel_timeline(BPM, 2)
    n = int(timeline["duration"] * SR)
    loud = analyze(_samples(np.full(n, 0.5)), timeline, [])  # -6 dBFS RMS -> 1.0
    assert loud.energy_hop == 0.1
    assert max(loud.energy) == pytest.approx(1.0, abs=0.01)
    assert len(loud.energy) == int(timeline["duration"] / 0.1) + 1
    quiet = analyze(_samples(np.full(n, 0.01)), timeline, [])  # -40 dBFS -> 0.0
    assert max(quiet.energy) == pytest.approx(0.0, abs=0.01)
    assert all(0.0 <= v <= 1.0 for v in loud.energy + quiet.energy)


def test_waveform_envelope_has_at_most_1000_points() -> None:
    timeline = reel_timeline(BPM, 4)
    report = analyze(_samples(kick_train(BPM, 4)), timeline, [])
    assert len(report.waveform) == 1000
    assert max(report.waveform) <= 1.0 and max(report.waveform) > 0.5
    short = analyze(
        _samples(np.full(300, 0.1)), {**timeline, "duration": 300 / SR, "sections": []}, []
    )
    assert len(short.waveform) == 300


def test_section_stats_and_energy_trend_warning() -> None:
    timeline = reel_timeline(BPM, 4, sections=2)
    n = len(kick_train(BPM, 4))
    data = np.concatenate([kick_train(BPM, 2) * 1.0, kick_train(BPM, 2) * 0.1])[:n]
    report = analyze(_samples(data), timeline, [], section_energy={"s1": "low", "s2": "peak"})
    assert [s.id for s in report.sections] == ["s1", "s2"]
    assert report.sections[0].rms_dbfs > report.sections[1].rms_dbfs
    assert any("s1" in w and "s2" in w and "RMS" in w for w in report.warnings)


def test_stereo_input_is_analysed_through_the_mono_mix() -> None:
    timeline = reel_timeline(BPM, 2)
    mono = kick_train(BPM, 2)
    report = analyze(_samples(np.stack([mono, mono], axis=1)), timeline, kick_events(BPM, 2))
    assert report.channels == 2
    assert report.grid_alignment is not None and report.grid_alignment > 0.9


# ---- validate_events ------------------------------------------------------------


def _doc(**overrides):
    doc = {"bpm": BPM, "duration": reel_timeline(BPM, 2)["duration"], "events": kick_events(BPM, 2)}
    doc.update(overrides)
    return doc


def test_valid_events_document_has_no_problems() -> None:
    assert validate_events(_doc(), reel_timeline(BPM, 2)) == []


@pytest.mark.parametrize(
    ("doc", "needle"),
    [
        ([], "对象"),
        (_doc(events="x"), "events"),
        (_doc(bpm=100.0), "bpm"),
        (_doc(duration=99.0), "duration"),
        (_doc(events=[{"name": "", "kind": "onset", "start": 0, "end": 1}]), "名称"),
        (_doc(events=[{"name": "k", "kind": "boom", "start": 0, "end": 1}]), "kind"),
        (_doc(events=[{"name": "k", "kind": "onset", "start": 2, "end": 1}]), "起止"),
        (_doc(events=[{"name": "k", "kind": "onset", "start": 0, "end": 99}]), "超出"),
    ],
)
def test_invalid_events_documents_are_reported(doc, needle: str) -> None:
    problems = validate_events(doc, reel_timeline(BPM, 2))
    assert any(needle in p for p in problems), problems


def test_narration_projects_do_not_compare_bpm_but_need_one() -> None:
    timeline = reel_timeline(BPM, 2)
    timeline = {
        **timeline,
        "grid": None,
        "narration": [{"scene_id": "s1", "start": 0, "end": 3.75, "beats": []}],
    }
    assert validate_events(_doc(bpm=100.0), timeline) == []
    assert any("bpm" in p for p in validate_events(_doc(bpm="fast"), timeline))


def _event(**overrides):
    return {"name": "k", "kind": "onset", "start": 0.0, "end": 0.5, **overrides}


@pytest.mark.parametrize(
    "doc",
    [
        _doc(bpm=float("nan")),
        _doc(duration=float("nan")),
        _doc(events=[_event(start=float("nan"), end=float("nan"))]),
        _doc(events=[_event(end=float("inf"))]),
    ],
)
def test_non_finite_declared_values_are_reported(doc) -> None:
    assert validate_events(doc, reel_timeline(BPM, 2))


@pytest.mark.parametrize(
    "offset", ["0.1", None, True, float("nan"), float("inf"), -1e7, -0.5, 99.0]
)
def test_an_unusable_offset_is_reported(offset) -> None:
    problems = validate_events(_doc(offset=offset), reel_timeline(BPM, 2))
    assert any("offset" in p for p in problems), problems


def test_a_sensible_offset_is_accepted() -> None:
    assert validate_events(_doc(offset=0.12), reel_timeline(BPM, 2)) == []
