"""`studio.timeline` 的 MV 来源：`imported.py` 与 `timed_sections`（4A 设计 §5）。"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from studio.timeline.build import (
    GridInput,
    MomentInput,
    NarrationInput,
    SectionInput,
    TimedSectionInput,
    TimelineError,
    TimelineLayers,
    build_timeline,
)
from studio.timeline.imported import (
    ImportLayers,
    downbeat_times,
    effective_grid,
    effective_range,
    layers_from_import,
)

BPM = 120.0  # beat 0.5 s, bar 2.0 s
HOP = 0.5
ENERGY = [round(i / 59, 6) for i in range(60)]  # 30 s at hop 0.5, value i/59 at index i

ANALYSIS: dict[str, Any] = {
    "source_hash": "a" * 64,
    "duration": 30.0,
    "bpm": BPM,
    "offset": 0.5,
    "residual_ms": 4.0,
    "confidence": 0.9,
    "beats": [0.5 + 0.5 * i for i in range(59)],
    "downbeats": [0.5 + 2.0 * i for i in range(15)],
    "candidates": [4.5, 8.5],
    "hop": HOP,
    "energy": ENERGY,
    "warnings": [],
}

SECTIONS: dict[str, Any] = {
    "sections": [
        {"id": "intro", "label": "Intro", "start": 0.5, "end": 4.5},
        {"id": "verse", "label": "Verse", "start": 4.5, "end": 8.5},
        {"id": "chorus", "label": "Chorus", "start": 8.5, "end": 12.5},
    ]
}

BEATSHEET: dict[str, Any] = {
    "sections": [
        {"ref": "intro", "intent": "起", "energy": "low", "moments": []},
        {
            "ref": "verse",
            "intent": "承",
            "energy": "mid",
            "moments": [{"at": "1.1", "visual_action": "镜头推近"}],
        },
        {
            "ref": "chorus",
            "intent": "爆",
            "energy": "peak",
            "moments": [{"at": "2.1", "visual_action": "几何体炸开"}],
        },
    ]
}


def _sections(**overrides: Any) -> dict[str, Any]:
    doc = copy.deepcopy(SECTIONS)
    doc.update(overrides)
    return doc


def _analysis(**overrides: Any) -> dict[str, Any]:
    doc = copy.deepcopy(ANALYSIS)
    doc.update(overrides)
    return doc


def _build(
    analysis: dict[str, Any] | None = None,
    sections: dict[str, Any] | None = None,
    beatsheet: dict[str, Any] | None = BEATSHEET,
) -> tuple[ImportLayers, Any]:
    layers = layers_from_import(
        analysis if analysis is not None else ANALYSIS,
        sections if sections is not None else SECTIONS,
        beatsheet,
        source_file="music/source.mp3",
    )
    return layers, build_timeline(layers.layers)


# --- effective_grid / downbeat_times ------------------------------------------------


def test_effective_grid_prefers_sections_overrides() -> None:
    assert effective_grid(ANALYSIS, SECTIONS) == (BPM, 0.5)
    assert effective_grid(ANALYSIS, _sections(bpm=100)) == (100.0, 0.5)
    assert effective_grid(ANALYSIS, _sections(bpm=100, offset=1.25)) == (100.0, 1.25)


@pytest.mark.parametrize(
    ("analysis", "sections"),
    [
        (_analysis(bpm="fast"), SECTIONS),
        (_analysis(bpm=None), SECTIONS),
        (_analysis(offset=float("nan")), SECTIONS),
        (ANALYSIS, _sections(bpm=True)),
        (ANALYSIS, _sections(bpm=300)),
        (ANALYSIS, _sections(offset="0")),
        ({}, {}),
    ],
)
def test_effective_grid_rejects_malformed_values(
    analysis: dict[str, Any], sections: dict[str, Any]
) -> None:
    with pytest.raises(TimelineError):
        effective_grid(analysis, sections)


def test_effective_grid_rejects_non_dict_documents() -> None:
    not_a_dict: Any = []
    with pytest.raises(TimelineError):
        effective_grid(not_a_dict, SECTIONS)
    with pytest.raises(TimelineError):
        effective_grid(ANALYSIS, not_a_dict)


def test_downbeat_times_cover_the_song() -> None:
    assert downbeat_times(BPM, 0.5, 6.5) == pytest.approx([0.5, 2.5, 4.5, 6.5])
    # an offset beyond the first bar extends the grid backwards to t >= 0
    assert downbeat_times(BPM, 3.0, 6.0) == pytest.approx([1.0, 3.0, 5.0])


@pytest.mark.parametrize(
    ("bpm", "offset", "duration"),
    [(0, 0, 10), (-120, 0, 10), (float("nan"), 0, 10), (120, float("inf"), 10), ("x", 0, 10)],
)
def test_downbeat_times_rejects_malformed_input(bpm: Any, offset: Any, duration: Any) -> None:
    with pytest.raises(TimelineError):
        downbeat_times(bpm, offset, duration)


# --- layers_from_import / build_timeline --------------------------------------------


def test_without_range_the_span_of_sections_is_the_timeline() -> None:
    layers, tl = _build()
    assert layers.source_hash == "a" * 64
    assert layers.range == (0.5, 12.5)
    assert layers.source_file == "music/source.mp3"
    assert tl.duration == pytest.approx(12.0)
    assert [(s.id, s.label, s.start, s.end) for s in tl.sections] == [
        ("intro", "Intro", 0.0, 4.0),
        ("verse", "Verse", 4.0, 8.0),
        ("chorus", "Chorus", 8.0, 12.0),
    ]
    assert tl.narration == []
    assert tl.grid is not None
    assert tl.grid.bpm == BPM and tl.grid.offset == 0.0
    assert tl.grid.downbeats == pytest.approx([0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0])
    assert tl.music is not None
    assert tl.music.file == "music/source.mp3"
    assert tl.music.events == []
    assert tl.music.energy.hop == HOP
    assert tl.music.energy.values == ENERGY[1 : 1 + 24]


def test_range_shifts_the_origin_and_drops_sections_outside_it() -> None:
    layers, tl = _build(sections=_sections(range={"start": 4.5, "end": 12.5}), beatsheet=None)
    assert layers.range == (4.5, 12.5)
    assert [(s.id, s.start, s.end) for s in tl.sections] == [
        ("verse", 0.0, 4.0),
        ("chorus", 4.0, 8.0),
    ]
    assert tl.duration == pytest.approx(8.0)
    assert tl.music is not None
    assert len(tl.music.energy.values) == round(8.0 / HOP)
    assert tl.music.energy.values == ENERGY[9 : 9 + 16]


def test_range_clips_sections_that_straddle_it() -> None:
    _, tl = _build(sections=_sections(range={"start": 2.5, "end": 10.5}), beatsheet=None)
    assert [(s.id, s.start, s.end) for s in tl.sections] == [
        ("intro", 0.0, 2.0),
        ("verse", 2.0, 6.0),
        ("chorus", 6.0, 8.0),
    ]
    assert tl.duration == pytest.approx(8.0)


def test_grid_offset_is_the_first_downbeat_after_the_range_start() -> None:
    doc = _sections(
        sections=[
            {"id": "a", "label": "A", "start": 1.5, "end": 4.5},
            {"id": "b", "label": "B", "start": 4.5, "end": 8.5},
        ]
    )
    _, tl = _build(sections=doc, beatsheet=None)
    assert tl.grid is not None
    assert tl.grid.offset == pytest.approx(1.0)
    assert tl.grid.downbeats[:2] == pytest.approx([1.0, 3.0])


def test_sections_overrides_drive_the_grid_and_moments() -> None:
    bar = 4 * 60 / 100
    doc = _sections(
        bpm=100,
        offset=1.0,
        sections=[
            {"id": "intro", "label": "I", "start": 1.0, "end": 1.0 + 2 * bar},
            {"id": "verse", "label": "V", "start": 1.0 + 2 * bar, "end": 1.0 + 4 * bar},
            {"id": "chorus", "label": "C", "start": 1.0 + 4 * bar, "end": 1.0 + 6 * bar},
        ],
    )
    _, tl = _build(sections=doc)
    assert tl.grid is not None
    assert tl.grid.bpm == 100.0 and tl.grid.offset == 0.0
    assert tl.grid.downbeats[1] == pytest.approx(bar)
    chorus_moment = tl.moments[-1]
    assert chorus_moment.t == pytest.approx(4 * bar + bar)  # "2.1" = one bar into chorus


def test_beatsheet_at_is_converted_relative_to_its_section() -> None:
    _, tl = _build()
    assert [(m.section_id, m.at, m.t, m.visual_action) for m in tl.moments] == [
        ("verse", "1.1", pytest.approx(4.0), "镜头推近"),
        ("chorus", "2.1", pytest.approx(10.0), "几何体炸开"),
    ]


def test_moment_outside_its_section_is_an_error() -> None:
    beatsheet = copy.deepcopy(BEATSHEET)
    beatsheet["sections"][2]["moments"] = [{"at": "3.1", "visual_action": "x"}]
    with pytest.raises(TimelineError) as info:
        _build(beatsheet=beatsheet)
    assert "chorus" in str(info.value) and "落在本段内" in str(info.value)


def test_ref_to_a_missing_section_is_an_error() -> None:
    beatsheet = copy.deepcopy(BEATSHEET)
    beatsheet["sections"][1]["ref"] = "bridge"
    with pytest.raises(TimelineError) as info:
        _build(beatsheet=beatsheet)
    assert "bridge" in str(info.value)


def test_beatsheet_section_without_ref_is_an_error() -> None:
    beatsheet = copy.deepcopy(BEATSHEET)
    del beatsheet["sections"][0]["ref"]
    beatsheet["sections"][0]["bars"] = 2
    with pytest.raises(TimelineError) as info:
        _build(beatsheet=beatsheet)
    assert "ref" in str(info.value)


def test_several_problems_are_reported_together() -> None:
    beatsheet = copy.deepcopy(BEATSHEET)
    beatsheet["sections"][0]["ref"] = "nope"
    beatsheet["sections"][2]["moments"] = [{"at": "9.1", "visual_action": "x"}]
    with pytest.raises(TimelineError) as info:
        _build(beatsheet=beatsheet)
    assert len(info.value.errors) >= 2


@pytest.mark.parametrize(
    ("analysis", "sections", "needle"),
    [
        (ANALYSIS, {"sections": []}, "sections"),
        (ANALYSIS, {"sections": "x"}, "sections"),
        (ANALYSIS, _sections(sections=[{"id": "a", "start": "0", "end": 2}]), "a"),
        (ANALYSIS, _sections(range={"start": 8.5, "end": 4.5}), "range"),
        (ANALYSIS, _sections(range=[0, 1]), "range"),
        (ANALYSIS, _sections(range={"start": 20.5, "end": 24.5}), "range"),
        (ANALYSIS, _sections(range={"start": 0.5, "end": 16.5}), "range"),
        (ANALYSIS, _sections(range={"start": 4.5, "end": 40.5}), "duration"),
        (_analysis(energy="loud"), SECTIONS, "energy"),
        (_analysis(hop=0), SECTIONS, "hop"),
        (_analysis(source_hash=None), SECTIONS, "source_hash"),
        (_analysis(duration=None), SECTIONS, "duration"),
    ],
)
def test_malformed_documents_are_timeline_errors(
    analysis: dict[str, Any], sections: dict[str, Any], needle: str
) -> None:
    with pytest.raises(TimelineError) as info:
        _build(analysis=analysis, sections=sections, beatsheet=None)
    assert needle in str(info.value)


# --- build_timeline with timed sections --------------------------------------------


def _timed(*sections: TimedSectionInput, **overrides: Any) -> TimelineLayers:
    base: dict[str, Any] = {
        "narration": [],
        "grid": GridInput(BPM),
        "timed_sections": list(sections),
    }
    base.update(overrides)
    return TimelineLayers(**base)


def test_timed_sections_keep_their_times() -> None:
    tl = build_timeline(
        _timed(TimedSectionInput("a", "A", 0.0, 2.0), TimedSectionInput("b", "B", 2.0, 6.0))
    )
    assert tl.duration == 6.0
    assert [(s.id, s.start, s.end) for s in tl.sections] == [("a", 0.0, 2.0), ("b", 2.0, 6.0)]


@pytest.mark.parametrize(
    ("sections", "needle"),
    [
        ((TimedSectionInput("a", "A", 0.0, 2.0), TimedSectionInput("b", "B", 2.5, 6.0)), "b"),
        ((TimedSectionInput("a", "A", 0.0, 2.0), TimedSectionInput("b", "B", 1.5, 6.0)), "b"),
        ((TimedSectionInput("a", "A", 0.0, 2.0), TimedSectionInput("a", "B", 2.0, 6.0)), "重复"),
        ((TimedSectionInput("a b", "A", 0.0, 2.0),), "镜头 id"),
        ((TimedSectionInput("a", "A", 0.0, 0.0),), "a"),
        ((TimedSectionInput("a", "A", 1.0, 2.0),), "从 0 开始"),
        ((), "没有任何镜头"),
    ],
)
def test_invalid_timed_sections_are_reported(
    sections: tuple[TimedSectionInput, ...], needle: str
) -> None:
    with pytest.raises(TimelineError) as info:
        build_timeline(_timed(*sections))
    assert needle in str(info.value)


def test_timed_sections_exclude_other_section_kinds() -> None:
    timed = TimedSectionInput("a", "A", 0.0, 2.0)
    with pytest.raises(TimelineError):
        build_timeline(_timed(timed, sections=[SectionInput("s", "S", 1)]))
    with pytest.raises(TimelineError):
        build_timeline(_timed(timed, narration=[NarrationInput("n", "N", 2.0, [])]))


def test_moments_resolve_against_timed_sections() -> None:
    tl = build_timeline(
        _timed(
            TimedSectionInput("a", "A", 0.0, 2.0),
            TimedSectionInput("b", "B", 2.0, 6.0),
            moments=[MomentInput("b", "2.2", "x")],
        )
    )
    assert tl.moments[0].t == pytest.approx(2.0 + 2.0 + 0.5)


def test_effective_range_prefers_explicit_range_else_section_span() -> None:
    sections = [
        {"id": "a", "label": "a", "start": 1.0, "end": 5.0},
        {"id": "b", "label": "b", "start": 5.0, "end": 9.0},
    ]
    assert effective_range({"sections": sections}) == (1.0, 9.0)
    explicit = {"sections": sections, "range": {"start": 1.0, "end": 5.0}}
    assert effective_range(explicit) == (1.0, 5.0)
    with pytest.raises(TimelineError):
        effective_range({"sections": []})
