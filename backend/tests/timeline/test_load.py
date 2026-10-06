"""`studio.timeline.load`：从工作区顶层 `narrative/` 读出时间轴（worker 与预览端点共用）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from studio.timeline import TimelineError
from studio.timeline.load import (
    LoadedTimeline,
    TimelineSources,
    load_timeline,
    load_workspace_timeline,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "animation"


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    narrative = tmp_path / "narrative"
    narrative.mkdir()
    for name in ("narrative.json", "timing.json"):
        shutil.copyfile(FIXTURES / name, narrative / name)
    return tmp_path


def test_loads_timeline_and_both_documents(workdir: Path) -> None:
    loaded = load_workspace_timeline(workdir)
    assert [s.id for s in loaded.timeline.sections] == ["s-hook", "s-explain"]
    assert loaded.timeline.duration == pytest.approx(3.0)
    assert loaded.timing["scenes"][0]["audio_path"] == "narrative/audio/s-hook.wav"
    assert len(loaded.hash) == 64


@pytest.mark.parametrize("name", ["narrative.json", "timing.json"])
def test_missing_document_names_the_file(workdir: Path, name: str) -> None:
    (workdir / "narrative" / name).unlink()
    with pytest.raises(TimelineError) as info:
        load_workspace_timeline(workdir)
    assert f"narrative/{name}" in str(info.value)


def test_broken_json_is_a_timeline_error(workdir: Path) -> None:
    (workdir / "narrative" / "timing.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(TimelineError) as info:
        load_workspace_timeline(workdir)
    assert "timing.json" in str(info.value)


def test_inconsistent_documents_report_the_scene(workdir: Path) -> None:
    path = workdir / "narrative" / "timing.json"
    timing = json.loads(path.read_text(encoding="utf-8"))
    timing["scenes"] = timing["scenes"][:1]
    path.write_text(json.dumps(timing), encoding="utf-8")
    with pytest.raises(TimelineError) as info:
        load_workspace_timeline(workdir)
    assert "s-explain" in str(info.value)


def test_symlink_pointing_outside_the_workspace_is_rejected(
    workdir: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "narrative.json"
    shutil.copyfile(FIXTURES / "narrative.json", outside)
    target = workdir / "narrative" / "narrative.json"
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(TimelineError) as info:
        load_workspace_timeline(workdir)
    assert "narrative.json" in str(info.value)


# --- MV (music_source="import"; 4A design §5) ---------------------------------------

_MV_ANALYSIS = {
    "source_hash": "a" * 64,
    "duration": 30.0,
    "bpm": 120.0,
    "offset": 0.5,
    "residual_ms": 4.0,
    "confidence": 0.9,
    "beats": [0.5 + 0.5 * i for i in range(59)],
    "downbeats": [0.5 + 2.0 * i for i in range(15)],
    "candidates": [4.5, 8.5],
    "hop": 0.5,
    "energy": [0.5] * 60,
    "warnings": [],
}
_MV_SECTIONS = {
    "sections": [
        {"id": "intro", "label": "Intro", "start": 0.5, "end": 4.5},
        {"id": "verse", "label": "Verse", "start": 4.5, "end": 8.5},
    ]
}
_MV_BEATSHEET = {
    "sections": [
        {"ref": "intro", "intent": "起", "energy": "low", "moments": []},
        {
            "ref": "verse",
            "intent": "承",
            "energy": "mid",
            "moments": [{"at": "1.3", "visual_action": "闪"}],
        },
    ]
}


def _write_json(root: Path, relpath: str, data: object) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load_mv(root: Path, *, prefix: str = "", with_music: bool = True) -> LoadedTimeline:
    return load_timeline(
        TimelineSources(
            root, narration=False, music_source="import", prefix=prefix, with_music=with_music
        )
    )


def _hash_after(mv: Path, relpath: str, **changes: object) -> str:
    document = json.loads((mv / relpath).read_text(encoding="utf-8"))
    document.update(changes)
    _write_json(mv, relpath, document)
    return _load_mv(mv).hash
