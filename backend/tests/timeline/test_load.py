"""`studio.timeline.load`：从工作区顶层 `narrative/` 读出时间轴（worker 与预览端点共用）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from studio.timeline import TimelineError
from studio.timeline.load import load_workspace_timeline

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
