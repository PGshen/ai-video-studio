"""`studio.timeline.build`：网格、节拍脚本点、配乐三层（子项目 3 设计 §4.1）。"""

from __future__ import annotations

from typing import Any

import pytest

from studio.timeline.build import (
    GridInput,
    MomentInput,
    MusicInput,
    NarrationInput,
    SectionInput,
    TimelineError,
    TimelineLayers,
    build_timeline,
)

BPM = 128.0
BEAT = 60 / BPM
BAR = 4 * BEAT


def _reel_layers(**overrides: Any) -> TimelineLayers:
    base: dict[str, Any] = {
        "narration": [],
        "sections": [SectionInput("s1-intro", "INTRO", 2), SectionInput("s2-drop", "DROP", 2)],
        "grid": GridInput(BPM),
        "moments": [
            MomentInput("s1-intro", "1.1", "标题淡入"),
            MomentInput("s2-drop", "2.3", "几何体脉动"),
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
        "declared_duration": 4 * BAR,
        "declared_bpm": BPM,
    }
    base.update(overrides)
    return MusicInput(**base)


def test_reel_sections_follow_bars_and_bpm() -> None:
    tl = build_timeline(_reel_layers())
    assert tl.duration == pytest.approx(4 * BAR)
    assert [(s.id, s.label) for s in tl.sections] == [("s1-intro", "INTRO"), ("s2-drop", "DROP")]
    assert tl.sections[0].start == 0.0
    assert tl.sections[0].end == pytest.approx(2 * BAR)
    assert tl.sections[1].start == pytest.approx(2 * BAR)
    assert tl.narration == []


def test_reel_grid_covers_the_whole_piece_plus_one_beat() -> None:
    tl = build_timeline(_reel_layers())
    grid = tl.grid
    assert grid is not None
    assert grid.bpm == BPM and grid.offset == 0.0
    assert len(grid.beats) == 4 * 4 + 1  # 4 bars = 16 beats, plus the closing beat
    assert grid.beats[1] == pytest.approx(BEAT)
    assert grid.beats[-1] == pytest.approx(tl.duration)
    assert grid.downbeats == pytest.approx([i * BAR for i in range(5)])


def test_moments_are_converted_to_global_seconds() -> None:
    tl = build_timeline(_reel_layers())
    first, second = tl.moments
    assert (first.section_id, first.at, first.t) == ("s1-intro", "1.1", pytest.approx(0.0))
    assert second.t == pytest.approx(
        2 * BAR + BAR + 2 * BEAT
    )  # section 2 starts at 2 bars; 2.3 = bar 2, beat 3
    assert second.visual_action == "几何体脉动"


def test_music_layer_maps_events_and_energy() -> None:
    tl = build_timeline(_reel_layers(music=_music()))
    assert tl.music is not None
    assert tl.music.file == "music/music.wav"
    assert [(e.name, e.kind) for e in tl.music.events] == [("kick", "onset"), ("riser", "sweep")]
    assert tl.music.energy.hop == 0.1
    assert tl.music.energy.values == [0.1, 0.5, 1.0]


def test_narration_project_gets_a_grid_from_the_declared_bpm() -> None:
    narration = [NarrationInput("s-a", "甲", 4.0, [(0.0, 1.0, "一")])]
    tl = build_timeline(
        TimelineLayers(
            narration=narration,
            grid=GridInput(120.0, offset=0.25),
            music=_music(declared_duration=4.0, declared_bpm=None, events=[]),
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
        (_reel_layers(grid=GridInput(20.0)), "BPM"),
        (_reel_layers(grid=GridInput(300.0)), "BPM"),
        (_reel_layers(sections=[SectionInput("s1-intro", "I", 0)]), "bars"),
        (_reel_layers(sections=[SectionInput("s 1", "I", 2)]), "镜头 id"),
        (_reel_layers(moments=[MomentInput("s1-intro", "9.1", "x")]), "落在本段内"),
        (_reel_layers(moments=[MomentInput("s1-intro", "x.y", "x")]), "小节.拍"),
        (_reel_layers(moments=[MomentInput("nope", "1.1", "x")]), "nope"),
        (_reel_layers(grid=None), "网格"),
        (
            _reel_layers(
                music=_music(events=[{"name": "", "kind": "onset", "start": 0, "end": 1}])
            ),
            "名称",
        ),
        (
            _reel_layers(
                music=_music(events=[{"name": "k", "kind": "boom", "start": 0, "end": 1}])
            ),
            "kind",
        ),
        (
            _reel_layers(
                music=_music(events=[{"name": "k", "kind": "onset", "start": 2, "end": 1}])
            ),
            "起止",
        ),
        (
            _reel_layers(
                music=_music(events=[{"name": "k", "kind": "onset", "start": 0, "end": 99}])
            ),
            "超出",
        ),
        (_reel_layers(music=_music(declared_duration=99.0)), "duration"),
        (_reel_layers(music=_music(declared_bpm=100.0)), "bpm"),
        (_reel_layers(music=_music(energy_hop=0.0)), "energy"),
    ],
)
def test_invalid_layers_are_reported(layers: TimelineLayers, needle: str) -> None:
    with pytest.raises(TimelineError) as info:
        build_timeline(layers)
    assert needle in str(info.value)


def test_several_problems_are_reported_together() -> None:
    layers = _reel_layers(
        moments=[MomentInput("s1-intro", "9.1", "x"), MomentInput("nope", "1.1", "y")],
        music=_music(declared_duration=99.0),
    )
    with pytest.raises(TimelineError) as info:
        build_timeline(layers)
    assert len(info.value.errors) >= 3


def test_sections_and_narration_together_are_rejected() -> None:
    layers = _reel_layers(narration=[NarrationInput("s-a", "甲", 2.0, [])])
    with pytest.raises(TimelineError):
        build_timeline(layers)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_music_values_are_rejected(bad: float) -> None:
    with pytest.raises(TimelineError):
        build_timeline(
            _reel_layers(
                music=_music(events=[{"name": "kick", "kind": "onset", "start": bad, "end": bad}])
            )
        )
    with pytest.raises(TimelineError):
        build_timeline(_reel_layers(music=_music(declared_duration=bad)))


def test_a_flood_of_bad_music_events_gives_a_short_message() -> None:
    bad = [{"name": "k" * 500, "kind": "boom", "start": 0, "end": 1}] * 5000
    with pytest.raises(TimelineError) as info:
        build_timeline(_reel_layers(music=_music(events=bad)))
    assert len(str(info.value)) < 8000 and "还有" in str(info.value)
