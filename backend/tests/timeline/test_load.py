"""`studio.timeline.load`：从工作区顶层 `narrative/` 读出时间轴（worker 与预览端点共用）。"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from studio.timeline import TimelineError
from studio.timeline.build import timeline_hash
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


@pytest.fixture
def mv(tmp_path: Path) -> Path:
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "source.mp3").write_bytes(b"ID3fake")
    _write_json(tmp_path, "music/analysis.json", _MV_ANALYSIS)
    _write_json(tmp_path, "music/sections.json", _MV_SECTIONS)
    _write_json(tmp_path, "beatsheet/beatsheet.json", _MV_BEATSHEET)
    return tmp_path


def _load_mv(root: Path, *, prefix: str = "", with_music: bool = True) -> LoadedTimeline:
    return load_timeline(
        TimelineSources(
            root, narration=False, music_source="import", prefix=prefix, with_music=with_music
        )
    )


def test_mv_timeline_is_loaded_from_music_and_beatsheet(mv: Path) -> None:
    loaded = _load_mv(mv)
    tl = loaded.timeline
    assert [(s.id, s.start, s.end) for s in tl.sections] == [
        ("intro", 0.0, 4.0),
        ("verse", 4.0, 8.0),
    ]
    assert tl.music is not None and tl.music.file == "music/source.mp3"
    assert tl.moments[0].t == pytest.approx(4.0 + 1.0)
    assert loaded.beatsheet == _MV_BEATSHEET
    assert loaded.hash == loaded.base_hash
    assert len(loaded.hash) == 64
    expected = hashlib.sha256(
        (timeline_hash(tl) + "a" * 64 + "0.500000-8.500000").encode("utf-8")
    ).hexdigest()
    assert loaded.hash == expected


def test_mv_reads_the_upstream_prefix(mv: Path) -> None:
    upstream = mv / "upstream"
    upstream.mkdir()
    for name in ("music", "beatsheet"):
        shutil.move(str(mv / name), str(upstream / name))
    loaded = _load_mv(mv, prefix="upstream/")
    assert loaded.timeline.music is not None
    assert loaded.timeline.music.file == "music/source.mp3"


def test_mv_without_music_layer_does_not_need_the_beatsheet(mv: Path) -> None:
    (mv / "beatsheet" / "beatsheet.json").unlink()
    loaded = _load_mv(mv, with_music=False)
    assert loaded.timeline.music is None
    assert loaded.timeline.moments == []
    assert loaded.beatsheet is None
    assert [s.id for s in loaded.timeline.sections] == ["intro", "verse"]
    assert loaded.hash == loaded.base_hash


def _hash_after(mv: Path, relpath: str, **changes: object) -> str:
    document = json.loads((mv / relpath).read_text(encoding="utf-8"))
    document.update(changes)
    _write_json(mv, relpath, document)
    return _load_mv(mv).hash


@pytest.mark.parametrize(
    ("relpath", "changes"),
    [
        ("music/sections.json", {"range": {"start": 2.5, "end": 8.5}}),
        ("music/sections.json", {"bpm": 121.0}),
        ("music/analysis.json", {"source_hash": "b" * 64}),
        ("music/analysis.json", {"bpm": 119.0}),
    ],
)
def test_mv_hash_follows_range_bpm_and_source(
    mv: Path, relpath: str, changes: dict[str, object]
) -> None:
    before = _load_mv(mv).hash
    assert _hash_after(mv, relpath, **changes) != before


@pytest.mark.parametrize(
    ("relpath", "changes"),
    [
        ("music/analysis.json", {"warnings": ["低置信"], "candidates": [12.5]}),
        ("music/analysis.json", {"residual_ms": 9.0, "confidence": 0.2}),
        ("music/sections.json", {"note": "无关键"}),
        ("music/sections.json", {"range": {"start": 0.5, "end": 8.5}}),
    ],
)
def test_mv_hash_ignores_fields_that_do_not_shape_the_timeline(
    mv: Path, relpath: str, changes: dict[str, object]
) -> None:
    before = _load_mv(mv).hash
    assert _hash_after(mv, relpath, **changes) == before


@pytest.mark.parametrize(
    "relpath", ["music/analysis.json", "music/sections.json", "beatsheet/beatsheet.json"]
)
def test_mv_missing_document_names_the_file(mv: Path, relpath: str) -> None:
    (mv / relpath).unlink()
    with pytest.raises(TimelineError) as info:
        _load_mv(mv)
    assert relpath in str(info.value)


def test_mv_missing_source_audio_is_an_error(mv: Path) -> None:
    (mv / "music" / "source.mp3").unlink()
    with pytest.raises(TimelineError) as info:
        _load_mv(mv)
    assert "music/source" in str(info.value)


def test_mv_broken_json_is_a_timeline_error(mv: Path) -> None:
    (mv / "music" / "sections.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(TimelineError) as info:
        _load_mv(mv)
    assert "sections.json" in str(info.value)


def test_mv_with_narration_is_not_supported(mv: Path) -> None:
    with pytest.raises(TimelineError) as info:
        load_timeline(TimelineSources(mv, narration=True, music_source="import"))
    assert "旁白" in str(info.value)
