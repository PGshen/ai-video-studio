"""`produce` 形态的时间轴读取与 `shots.json` / `range.json` 校验（produce-stage 设计 §5.3、§6）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from studio.timeline import TimelineError
from studio.timeline.load import TimelineSources, load_timeline
from studio.timeline.shots import parse_range, parse_shots

DURATION = 12.0
SHOTS: dict[str, Any] = {
    "shots": [
        {"id": "intro", "label": "INTRO", "start": 0.0, "end": 4.0},
        {"id": "drop", "label": "DROP", "start": 4.0, "end": 12.0},
    ]
}


def _write(root: Path, relpath: str, data: Any) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _synth(root: Path, *, duration: float = DURATION, shots: Any = SHOTS, bpm: Any = 120) -> None:
    events: dict[str, Any] = {
        "duration": duration,
        "events": [
            {"name": "kick", "kind": "onset", "start": 0.0, "end": 0.2},
            {"name": "riser", "kind": "sweep", "start": 2.0, "end": 4.0},
        ],
    }
    if bpm is not None:
        events["bpm"] = bpm
    _write(root, "music/events.json", events)
    _write(root, "music/analysis.json", {"hop": 0.5, "energy": [0.1] * 24, "duration": duration})
    if shots is not None:
        _write(root, "animation/shots.json", shots)


def _import(root: Path, *, range_doc: Any = None, shots: Any = SHOTS) -> None:
    beats = [round(0.5 * i, 3) for i in range(0, 80)]
    _write(
        root,
        "music/analysis.json",
        {
            "source_hash": "abc123",
            "duration": 40.0,
            "bpm": 120.0,
            "offset": 0.0,
            "hop": 0.5,
            "energy": [0.2] * 80,
            "beats": beats,
            "downbeats": beats[::4],
        },
    )
    (root / "music").mkdir(parents=True, exist_ok=True)
    (root / "music" / "source.mp3").write_bytes(b"fake")
    if range_doc is not None:
        _write(root, "music/range.json", range_doc)
    if shots is not None:
        _write(root, "animation/shots.json", shots)


def _sources(root: Path, music_source: str = "synth", **kw: Any) -> TimelineSources:
    return TimelineSources(
        root=root, narration=False, music_source=music_source, produce=True, **kw
    )


class TestParseShots:
    def test_valid_document(self) -> None:
        errors: list[str] = []
        shots = parse_shots(SHOTS, errors)
        assert errors == []
        assert shots is not None
        assert [(s.id, s.start, s.end) for s in shots] == [("intro", 0.0, 4.0), ("drop", 4.0, 12.0)]

    def test_label_defaults_to_the_id(self) -> None:
        errors: list[str] = []
        shots = parse_shots({"shots": [{"id": "a", "start": 0, "end": 1}]}, errors)
        assert errors == [] and shots is not None and shots[0].label == "a"

    @pytest.mark.parametrize(
        "doc, needle",
        [
            ([], "顶层"),
            ({}, "shots"),
            ({"shots": []}, "至少"),
            ({"shots": ["x"]}, "对象"),
            ({"shots": [{"id": "a", "start": 0}]}, "end"),
            ({"shots": [{"start": 0, "end": 1}]}, "id"),
            ({"shots": [{"id": "a", "start": "0", "end": 1}]}, "数字"),
        ],
    )
    def test_malformed_documents_name_the_problem(self, doc: Any, needle: str) -> None:
        errors: list[str] = []
        assert parse_shots(doc, errors) is None
        assert any(needle in error and "shots.json" in error for error in errors), errors

    def test_gaps_within_a_millisecond_are_snapped(self) -> None:
        errors: list[str] = []
        doc = {
            "shots": [
                {"id": "a", "start": 0, "end": 3.3333},
                {"id": "b", "start": 3.3338, "end": 6.0},
            ]
        }
        shots = parse_shots(doc, errors)
        assert errors == [] and shots is not None
        assert shots[1].start == shots[0].end


class TestParseRange:
    def test_missing_document_means_the_whole_song(self) -> None:
        errors: list[str] = []
        assert parse_range(None, 40.0, errors) == (0.0, 40.0) and errors == []

    def test_valid_range(self) -> None:
        errors: list[str] = []
        assert parse_range({"start": 5, "end": 25.5}, 40.0, errors) == (5.0, 25.5)

    @pytest.mark.parametrize(
        "doc",
        [
            {"start": -1, "end": 5},
            {"start": 10, "end": 10},
            {"start": 30, "end": 20},
            {"start": 0, "end": 41},
            {"start": "a", "end": 5},
            {"start": 0},
            [],
        ],
    )
    def test_invalid_ranges_are_reported(self, doc: Any) -> None:
        errors: list[str] = []
        assert parse_range(doc, 40.0, errors) is None
        assert errors and all("range.json" in error for error in errors)


class TestLoadSynth:
    def test_reads_shots_music_and_no_authored_layers(self, tmp_path: Path) -> None:
        _synth(tmp_path)
        loaded = load_timeline(_sources(tmp_path))
        timeline = loaded.timeline
        assert timeline.duration == DURATION
        assert [s.id for s in timeline.sections] == ["intro", "drop"]
        assert timeline.grid is None and timeline.moments == [] and timeline.narration == []
        assert timeline.music is not None
        assert [e.name for e in timeline.music.events] == ["kick", "riser"]
        assert loaded.hash == loaded.base_hash and loaded.range is None
        assert loaded.beatsheet is None

    def test_bpm_is_optional(self, tmp_path: Path) -> None:
        _synth(tmp_path, bpm=None)
        assert load_timeline(_sources(tmp_path)).timeline.music is not None

    def test_reads_under_a_prefix(self, tmp_path: Path) -> None:
        _synth(tmp_path / "upstream")
        loaded = load_timeline(_sources(tmp_path, prefix="upstream/"))
        assert loaded.timeline.duration == DURATION

    def test_hash_follows_the_shots(self, tmp_path: Path) -> None:
        _synth(tmp_path)
        first = load_timeline(_sources(tmp_path)).hash
        _write(
            tmp_path,
            "animation/shots.json",
            {"shots": [{"id": "all", "label": "ALL", "start": 0, "end": DURATION}]},
        )
        assert load_timeline(_sources(tmp_path)).hash != first

    def test_a_single_shot_is_fine(self, tmp_path: Path) -> None:
        _synth(tmp_path, shots={"shots": [{"id": "all", "start": 0, "end": DURATION}]})
        assert len(load_timeline(_sources(tmp_path)).timeline.sections) == 1

    def test_missing_shots_says_where_to_write_them(self, tmp_path: Path) -> None:
        _synth(tmp_path, shots=None)
        with pytest.raises(TimelineError, match=r"animation/shots\.json"):
            load_timeline(_sources(tmp_path))

    def test_missing_music_says_to_render_it(self, tmp_path: Path) -> None:
        _write(tmp_path, "animation/shots.json", SHOTS)
        with pytest.raises(TimelineError, match=r"render_music"):
            load_timeline(_sources(tmp_path))

    @pytest.mark.parametrize("last_end, needle", [(10.0, "10"), (14.5, "14.5")])
    def test_shots_not_covering_the_music_name_both_lengths(
        self, tmp_path: Path, last_end: float, needle: str
    ) -> None:
        shots = {
            "shots": [{"id": "a", "start": 0, "end": 4}, {"id": "b", "start": 4, "end": last_end}]
        }
        _synth(tmp_path, shots=shots)
        with pytest.raises(TimelineError) as caught:
            load_timeline(_sources(tmp_path))
        text = str(caught.value)
        assert "12" in text and needle in text

    def test_tail_within_tolerance_is_accepted(self, tmp_path: Path) -> None:
        shots = {
            "shots": [{"id": "a", "start": 0, "end": 4}, {"id": "b", "start": 4, "end": 12.03}]
        }
        _synth(tmp_path, shots=shots)
        assert load_timeline(_sources(tmp_path)).timeline.sections[-1].end == 12.03

    def test_gap_between_shots_is_reported(self, tmp_path: Path) -> None:
        shots = {"shots": [{"id": "a", "start": 0, "end": 4}, {"id": "b", "start": 5, "end": 12}]}
        _synth(tmp_path, shots=shots)
        with pytest.raises(TimelineError, match="不相接"):
            load_timeline(_sources(tmp_path))

    @pytest.mark.parametrize("bad_id", ["a b", "../x", "镜头"])
    def test_unsafe_ids_are_rejected(self, tmp_path: Path, bad_id: str) -> None:
        shots = {"shots": [{"id": bad_id, "start": 0, "end": 12}]}
        _synth(tmp_path, shots=shots)
        with pytest.raises(TimelineError, match="id"):
            load_timeline(_sources(tmp_path))


class TestLoadImport:
    def test_whole_song_when_there_is_no_range(self, tmp_path: Path) -> None:
        shots = {"shots": [{"id": "all", "start": 0, "end": 40}]}
        _import(tmp_path, shots=shots)
        loaded = load_timeline(_sources(tmp_path, "import"))
        assert loaded.timeline.duration == 40.0
        assert loaded.range == (0.0, 40.0) and loaded.source_hash == "abc123"
        assert loaded.timeline.music is not None
        assert loaded.timeline.music.file == "music/source.mp3"

    def test_beats_and_downbeats_become_events_shifted_by_the_range_start(
        self, tmp_path: Path
    ) -> None:
        _import(tmp_path, range_doc={"start": 10, "end": 22})
        loaded = load_timeline(_sources(tmp_path, "import"))
        music = loaded.timeline.music
        assert music is not None and loaded.range == (10.0, 22.0)
        beats = [e.start for e in music.events if e.name == "beat"]
        downbeats = [e.start for e in music.events if e.name == "downbeat"]
        assert beats[0] == 0.0 and beats[-1] <= 12.0 and len(beats) == 24
        assert downbeats[:3] == [0.0, 2.0, 4.0]
        assert all(e.kind == "onset" for e in music.events)
        assert loaded.timeline.grid is None and loaded.timeline.moments == []

    def test_energy_is_cut_to_the_range(self, tmp_path: Path) -> None:
        _import(tmp_path, range_doc={"start": 10, "end": 22})
        music = load_timeline(_sources(tmp_path, "import")).timeline.music
        assert music is not None and len(music.energy.values) == 24

    def test_hash_follows_the_range_and_the_source(self, tmp_path: Path) -> None:
        _import(tmp_path, range_doc={"start": 10, "end": 22})
        first = load_timeline(_sources(tmp_path, "import")).hash
        _write(tmp_path, "music/range.json", {"start": 11, "end": 23})
        assert load_timeline(_sources(tmp_path, "import")).hash != first

    def test_range_outside_the_song_is_an_error(self, tmp_path: Path) -> None:
        _import(tmp_path, range_doc={"start": 30, "end": 50})
        with pytest.raises(TimelineError, match=r"range\.json"):
            load_timeline(_sources(tmp_path, "import"))

    def test_shots_must_cover_the_range_length(self, tmp_path: Path) -> None:
        _import(tmp_path, range_doc={"start": 10, "end": 30})  # 20 s, shots cover 12 s
        with pytest.raises(TimelineError) as caught:
            load_timeline(_sources(tmp_path, "import"))
        assert "20" in str(caught.value) and "12" in str(caught.value)

    def test_missing_source_asks_for_an_upload(self, tmp_path: Path) -> None:
        _import(tmp_path)
        (tmp_path / "music" / "source.mp3").unlink()
        with pytest.raises(TimelineError, match="source"):
            load_timeline(_sources(tmp_path, "import"))

    def test_does_not_need_sections_json_or_a_beatsheet(self, tmp_path: Path) -> None:
        _import(tmp_path, range_doc={"start": 10, "end": 22})
        assert not (tmp_path / "music" / "sections.json").exists()
        assert not (tmp_path / "beatsheet").exists()
        load_timeline(_sources(tmp_path, "import"))
