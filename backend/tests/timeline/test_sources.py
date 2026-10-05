"""`studio.timeline.load.TimelineSources`：按项目形态读取时间轴（子项目 3 设计 §4.2）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from studio.timeline import TimelineError
from studio.timeline.load import TimelineSources, load_timeline

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "animation"
BPM = 128.0
BAR = 4 * 60 / BPM

BEATSHEET: dict[str, Any] = {
    "bpm": BPM,
    "sections": [
        {
            "id": "s1-intro",
            "label": "INTRO",
            "bars": 2,
            "intent": "起",
            "energy": "low",
            "moments": [{"at": "1.1", "visual_action": "标题淡入"}],
        },
        {
            "id": "s2-drop",
            "label": "DROP",
            "bars": 2,
            "intent": "爆",
            "energy": "peak",
            "moments": [],
        },
    ],
}


def _events(bpm: float = BPM, duration: float = 4 * BAR, **extra: Any) -> dict[str, Any]:
    return {
        "bpm": bpm,
        "duration": duration,
        "events": [{"name": "kick", "kind": "onset", "start": 0.0, "end": 0.2}],
        **extra,
    }


def _analysis() -> dict[str, Any]:
    return {"hop": 0.1, "energy": [0.2, 0.4, 0.9], "duration": 4 * BAR}


def _write(root: Path, relpath: str, data: Any) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _reel(root: Path, prefix: str = "") -> None:
    _write(root, f"{prefix}beatsheet/beatsheet.json", BEATSHEET)
    _write(root, f"{prefix}music/events.json", _events())
    _write(root, f"{prefix}music/analysis.json", _analysis())


def _explainer(root: Path, prefix: str = "", *, music: bool = True) -> None:
    for name in ("narrative.json", "timing.json"):
        target = root / f"{prefix}narrative" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / name, target)
    if music:
        _write(root, f"{prefix}music/events.json", _events(bpm=100.0, duration=3.0, offset=0.1))
        _write(root, f"{prefix}music/analysis.json", _analysis())


def _reel_sources(root: Path, **kw: Any) -> TimelineSources:
    return TimelineSources(root=root, narration=False, music_source="synth", **kw)


def _explainer_sources(root: Path, **kw: Any) -> TimelineSources:
    return TimelineSources(
        root=root, narration=True, music_source=kw.pop("music_source", "synth"), **kw
    )


def test_reel_reads_beatsheet_events_and_energy(tmp_path: Path) -> None:
    _reel(tmp_path)
    loaded = load_timeline(_reel_sources(tmp_path))
    tl = loaded.timeline
    assert [s.id for s in tl.sections] == ["s1-intro", "s2-drop"]
    assert tl.duration == pytest.approx(4 * BAR)
    assert tl.grid is not None and tl.grid.bpm == BPM
    assert [m.at for m in tl.moments] == ["1.1"]
    assert tl.music is not None and tl.music.energy.values == [0.2, 0.4, 0.9]
    assert loaded.beatsheet == BEATSHEET
    assert loaded.narrative == {} and loaded.timing == {}


def test_reel_reads_the_upstream_layout(tmp_path: Path) -> None:
    _reel(tmp_path, prefix="upstream/")
    loaded = load_timeline(_reel_sources(tmp_path, prefix="upstream/"))
    assert loaded.timeline.music is not None


def test_reel_without_music_for_the_music_stage_itself(tmp_path: Path) -> None:
    _write(tmp_path, "upstream/beatsheet/beatsheet.json", BEATSHEET)
    loaded = load_timeline(_reel_sources(tmp_path, prefix="upstream/", with_music=False))
    assert loaded.timeline.music is None
    assert loaded.timeline.grid is not None
    assert loaded.hash == loaded.base_hash


def test_base_hash_ignores_events_and_energy_but_hash_does_not(tmp_path: Path) -> None:
    _reel(tmp_path)
    first = load_timeline(_reel_sources(tmp_path))
    _write(tmp_path, "music/analysis.json", {**_analysis(), "energy": [0.9, 0.9, 0.9]})
    second = load_timeline(_reel_sources(tmp_path))
    assert first.base_hash == second.base_hash
    assert first.hash != second.hash
    assert first.base_hash != first.hash


def test_base_hash_changes_with_the_beatsheet(tmp_path: Path) -> None:
    _reel(tmp_path)
    first = load_timeline(_reel_sources(tmp_path))
    changed = {
        **BEATSHEET,
        "sections": [{**BEATSHEET["sections"][0], "bars": 3}, BEATSHEET["sections"][1]],
    }
    _write(tmp_path, "beatsheet/beatsheet.json", changed)
    _write(tmp_path, "music/events.json", _events(duration=5 * BAR))
    second = load_timeline(_reel_sources(tmp_path))
    assert first.base_hash != second.base_hash


def test_explainer_with_music_takes_the_grid_from_the_declared_bpm(tmp_path: Path) -> None:
    _explainer(tmp_path)
    loaded = load_timeline(_explainer_sources(tmp_path))
    tl = loaded.timeline
    assert tl.grid is not None and tl.grid.bpm == 100.0
    assert tl.grid.beats[0] == pytest.approx(0.1)
    assert tl.music is not None and len(tl.narration) == 2
    assert loaded.timing["scenes"][0]["audio_path"] == "narrative/audio/s-hook.wav"


def test_explainer_base_timeline_has_no_grid(tmp_path: Path) -> None:
    _explainer(tmp_path)
    full = load_timeline(_explainer_sources(tmp_path))
    base = load_timeline(_explainer_sources(tmp_path, with_music=False))
    assert base.timeline.grid is None and base.timeline.music is None
    assert full.base_hash == base.hash


def test_explainer_without_music_matches_the_plain_narration_timeline(tmp_path: Path) -> None:
    _explainer(tmp_path, music=False)
    loaded = load_timeline(_explainer_sources(tmp_path, music_source="none"))
    assert loaded.timeline.grid is None and loaded.timeline.music is None
    assert loaded.hash == loaded.base_hash


@pytest.mark.parametrize("name", ["events.json", "analysis.json"])
def test_missing_music_files_name_the_file(tmp_path: Path, name: str) -> None:
    _reel(tmp_path)
    (tmp_path / "music" / name).unlink()
    with pytest.raises(TimelineError) as info:
        load_timeline(_reel_sources(tmp_path))
    assert f"music/{name}" in str(info.value)


def test_missing_beatsheet_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(TimelineError) as info:
        load_timeline(_reel_sources(tmp_path, with_music=False))
    assert "beatsheet/beatsheet.json" in str(info.value)


def test_broken_json_and_wrong_shape_are_reported(tmp_path: Path) -> None:
    _reel(tmp_path)
    (tmp_path / "music" / "events.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(TimelineError):
        load_timeline(_reel_sources(tmp_path))
    _write(tmp_path, "music/events.json", _events())
    _write(tmp_path, "beatsheet/beatsheet.json", {"bpm": "fast", "sections": "x"})
    with pytest.raises(TimelineError):
        load_timeline(_reel_sources(tmp_path))


def test_symlink_out_of_the_workspace_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "work"
    _reel(root)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_analysis()), encoding="utf-8")
    (root / "music" / "analysis.json").unlink()
    (root / "music" / "analysis.json").symlink_to(outside)
    with pytest.raises(TimelineError) as info:
        load_timeline(_reel_sources(root))
    assert "工作区之外" in str(info.value)


def test_events_that_disagree_with_the_beatsheet_are_reported(tmp_path: Path) -> None:
    _reel(tmp_path)
    _write(tmp_path, "music/events.json", _events(bpm=100.0))
    with pytest.raises(TimelineError) as info:
        load_timeline(_reel_sources(tmp_path))
    assert "bpm" in str(info.value)


def test_legacy_entry_point_still_loads_the_narration_only_timeline(tmp_path: Path) -> None:
    from studio.timeline.load import load_workspace_timeline

    _explainer(tmp_path, music=False)
    assert load_workspace_timeline(tmp_path).timeline.grid is None
