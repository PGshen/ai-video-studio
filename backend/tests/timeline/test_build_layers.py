"""`studio.timeline.build`：网格与配乐层、镜头划分（子项目 3 设计 §4.1，produce 设计 §6）。"""

from __future__ import annotations

from typing import Any

import pytest

from studio.timeline.build import (
    GridInput,
    MusicInput,
    NarrationInput,
    TimedSectionInput,
    TimelineError,
    TimelineLayers,
    build_timeline,
)

DURATION = 8.0


def _shots(**overrides: Any) -> TimelineLayers:
    base: dict[str, Any] = {
        "narration": [],
        "timed_sections": [
            TimedSectionInput("s1-intro", "INTRO", 0.0, 3.0),
            TimedSectionInput("s2-drop", "DROP", 3.0, DURATION),
        ],
    }
    base.update(overrides)
    return TimelineLayers(**base)


def _music(**overrides: Any) -> MusicInput:
    base: dict[str, Any] = {
        "events": [
            {"name": "kick", "kind": "onset", "start": 0.0, "end": 0.2},
            {"name": "riser", "kind": "sweep", "start": 1.0, "end": 3.0},
        ],
        "energy_hop": 0.1,
        "energy_values": [0.1, 0.5, 1.0],
        "declared_duration": DURATION,
    }
    base.update(overrides)
    return MusicInput(**base)


def test_shots_keep_the_times_the_model_wrote() -> None:
    tl = build_timeline(_shots())
    assert tl.duration == pytest.approx(DURATION)
    assert [(s.id, s.label, s.start, s.end) for s in tl.sections] == [
        ("s1-intro", "INTRO", 0.0, 3.0),
        ("s2-drop", "DROP", 3.0, DURATION),
    ]
    assert tl.narration == [] and tl.grid is None and tl.moments == []


def test_music_layer_maps_events_and_energy() -> None:
    tl = build_timeline(_shots(music=_music()))
    assert tl.music is not None
    assert tl.music.file == "music/music.wav"
    assert [(e.name, e.kind) for e in tl.music.events] == [("kick", "onset"), ("riser", "sweep")]
    assert tl.music.energy.hop == 0.1
    assert tl.music.energy.values == [0.1, 0.5, 1.0]


def test_a_custom_music_file_is_kept() -> None:
    tl = build_timeline(_shots(music=_music(file="music/source.mp3")))
    assert tl.music is not None and tl.music.file == "music/source.mp3"


def test_narration_project_gets_a_grid_from_the_declared_bpm() -> None:
    narration = [NarrationInput("s-a", "甲", 4.0, [(0.0, 1.0, "一")])]
    tl = build_timeline(
        TimelineLayers(
            narration=narration,
            grid=GridInput(120.0, offset=0.25),
            music=_music(declared_duration=4.0, events=[]),
        )
    )
    assert tl.grid is not None
    assert tl.grid.beats[0] == pytest.approx(0.25)
    assert tl.grid.beats[1] == pytest.approx(0.75)
    assert 4.0 <= tl.grid.beats[-1] < 4.0 + 0.5  # covers the piece, plus at most one beat
    assert tl.grid.downbeats[1] == pytest.approx(0.25 + 2.0)
    assert tl.moments == []


def test_narration_project_without_music_has_no_grid() -> None:
    tl = build_timeline(TimelineLayers(narration=[NarrationInput("s-a", "甲", 2.0, [])]))
    assert tl.grid is None and tl.music is None and tl.moments == []


@pytest.mark.parametrize(
    ("layers", "needle"),
    [
        (_shots(grid=GridInput(20.0)), "BPM"),
        (_shots(grid=GridInput(300.0)), "BPM"),
        (_shots(timed_sections=[TimedSectionInput("s 1", "I", 0.0, 8.0)]), "镜头 id"),
        (_shots(timed_sections=[TimedSectionInput("../x", "I", 0.0, 8.0)]), "镜头 id"),
        (_shots(timed_sections=[TimedSectionInput("a", "I", 0.0, 4.0)] * 2), "重复"),
        (_shots(timed_sections=[TimedSectionInput("a", "I", 1.0, 8.0)]), "从 0 开始"),
        (
            _shots(
                timed_sections=[
                    TimedSectionInput("a", "A", 0.0, 3.0),
                    TimedSectionInput("b", "B", 4.0, 8.0),
                ]
            ),
            "不相接",
        ),
        (_shots(timed_sections=[TimedSectionInput("a", "I", 3.0, 3.0)]), "start < end"),
        (_shots(timed_sections=[]), "没有任何镜头"),
        (
            _shots(music=_music(events=[{"name": "", "kind": "onset", "start": 0, "end": 1}])),
            "名称",
        ),
        (
            _shots(music=_music(events=[{"name": "k", "kind": "boom", "start": 0, "end": 1}])),
            "kind",
        ),
        (
            _shots(music=_music(events=[{"name": "k", "kind": "onset", "start": 2, "end": 1}])),
            "起止",
        ),
        (
            _shots(music=_music(events=[{"name": "k", "kind": "onset", "start": 0, "end": 99}])),
            "超出",
        ),
        (_shots(music=_music(declared_duration=99.0)), "duration"),
        (_shots(music=_music(energy_hop=0.0)), "energy"),
    ],
)
def test_invalid_layers_are_reported(layers: TimelineLayers, needle: str) -> None:
    with pytest.raises(TimelineError) as info:
        build_timeline(layers)
    assert needle in str(info.value)


def test_several_problems_are_reported_together() -> None:
    layers = _shots(
        timed_sections=[
            TimedSectionInput("a b", "x", 0.0, 3.0),
            TimedSectionInput("c", "y", 4.0, 8.0),
        ],
        music=_music(declared_duration=99.0),
    )
    with pytest.raises(TimelineError) as info:
        build_timeline(layers)
    assert len(info.value.errors) >= 3


def test_shots_and_narration_together_are_rejected() -> None:
    layers = _shots(narration=[NarrationInput("s-a", "甲", 2.0, [])])
    with pytest.raises(TimelineError):
        build_timeline(layers)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_music_values_are_rejected(bad: float) -> None:
    with pytest.raises(TimelineError):
        build_timeline(
            _shots(
                music=_music(events=[{"name": "kick", "kind": "onset", "start": bad, "end": bad}])
            )
        )
    with pytest.raises(TimelineError):
        build_timeline(_shots(music=_music(declared_duration=bad)))


def test_a_flood_of_bad_music_events_gives_a_short_message() -> None:
    bad = [{"name": "k" * 500, "kind": "boom", "start": 0, "end": 1}] * 5000
    with pytest.raises(TimelineError) as info:
        build_timeline(_shots(music=_music(events=bad)))
    assert len(str(info.value)) < 8000 and "还有" in str(info.value)
