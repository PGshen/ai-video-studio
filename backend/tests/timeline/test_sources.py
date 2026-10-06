"""`studio.timeline.load.TimelineSources`：讲解 + 背景乐的时间轴读取（子项目 3 设计 §4.2）。

短片与 MV 的读取（`produce`）见 `test_shots.py`。
"""

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


def _explainer(root: Path, prefix: str = "", *, music: bool = True) -> None:
    for name in ("narrative.json", "timing.json"):
        target = root / f"{prefix}narrative" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / name, target)
    if music:
        _write(root, f"{prefix}music/events.json", _events(bpm=100.0, duration=3.0, offset=0.1))
        _write(root, f"{prefix}music/analysis.json", _analysis())


def _explainer_sources(root: Path, **kw: Any) -> TimelineSources:
    return TimelineSources(
        root=root, narration=True, music_source=kw.pop("music_source", "synth"), **kw
    )


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


def test_legacy_entry_point_still_loads_the_narration_only_timeline(tmp_path: Path) -> None:
    from studio.timeline.load import load_workspace_timeline

    _explainer(tmp_path, music=False)
    assert load_workspace_timeline(tmp_path).timeline.grid is None


def test_base_hash_ignores_events_and_energy_but_hash_does_not(tmp_path: Path) -> None:
    _explainer(tmp_path)
    first = load_timeline(_explainer_sources(tmp_path))
    _write(tmp_path, "music/analysis.json", {**_analysis(), "energy": [0.9, 0.9, 0.9]})
    second = load_timeline(_explainer_sources(tmp_path))
    assert first.base_hash == second.base_hash
    assert first.hash != second.hash
    assert first.base_hash != first.hash


@pytest.mark.parametrize("name", ["events.json", "analysis.json"])
def test_missing_music_files_name_the_file(tmp_path: Path, name: str) -> None:
    _explainer(tmp_path)
    (tmp_path / "music" / name).unlink()
    with pytest.raises(TimelineError) as info:
        load_timeline(_explainer_sources(tmp_path))
    assert f"music/{name}" in str(info.value)


def test_broken_json_is_reported(tmp_path: Path) -> None:
    _explainer(tmp_path)
    (tmp_path / "music" / "events.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(TimelineError):
        load_timeline(_explainer_sources(tmp_path))


def test_symlink_out_of_the_workspace_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "work"
    _explainer(root)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_analysis()), encoding="utf-8")
    (root / "music" / "analysis.json").unlink()
    (root / "music" / "analysis.json").symlink_to(outside)
    with pytest.raises(TimelineError) as info:
        load_timeline(_explainer_sources(root))
    assert "工作区之外" in str(info.value)


def test_a_silent_project_is_not_read_without_the_produce_flag(tmp_path: Path) -> None:
    with pytest.raises(TimelineError, match="produce"):
        load_timeline(TimelineSources(root=tmp_path, narration=False, music_source="synth"))
