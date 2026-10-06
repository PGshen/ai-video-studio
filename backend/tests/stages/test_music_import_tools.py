"""`analyze_music` (4A T5): source lookup, products, error forms, old products kept on failure."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from fixtures.import_music import BPM, OFFSET, write_click_song, write_silence
from studio.agent.tools import ToolContext, ToolResult, invoke_tool
from studio.engines.audio.song_job import SongJobError
from studio.stages.common.score import analyze as analyze_module
from studio.stages.common.score.analyze import ANALYZE_MUSIC_TOOL
from studio.stages.common.score.sources import SOURCE_EXTENSIONS, import_source


def doc_bpm(workdir: Path) -> float:
    return float(json.loads((workdir / "music" / "analysis.json").read_text())["bpm"])


def _ctx(workdir: Path, writes: list[tuple[str, str]]) -> ToolContext:
    return ToolContext(
        project_id="p",
        stage="produce",
        workdir=workdir,
        record_tool_write=lambda rel, digest: writes.append((rel, digest)),
    )


@pytest.fixture(scope="module")
def song(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_click_song(tmp_path_factory.mktemp("song") / "song.wav")


@pytest.fixture
def project(tmp_path: Path, song: Path) -> Path:
    (tmp_path / "music").mkdir()
    shutil.copyfile(song, tmp_path / "music" / "source.wav")
    return tmp_path


@pytest.fixture(scope="module")
def analyzed(song: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, ToolResult, list]:
    """One real analysis (numba cold start is ~27 s), shared by the read-only assertions."""
    import asyncio

    workdir = tmp_path_factory.mktemp("analyzed")
    (workdir / "music").mkdir()
    shutil.copyfile(song, workdir / "music" / "source.wav")
    writes: list[tuple[str, str]] = []
    result = asyncio.run(invoke_tool(ANALYZE_MUSIC_TOOL, _ctx(workdir, writes), {}))
    return workdir, result, writes


def test_import_source_finds_whitelisted_extensions(tmp_path: Path) -> None:
    assert import_source(tmp_path) is None
    (tmp_path / "music").mkdir()
    assert import_source(tmp_path) is None
    (tmp_path / "music" / "source.txt").write_text("x")
    assert import_source(tmp_path) is None
    for ext in SOURCE_EXTENSIONS:
        path = tmp_path / "music" / f"source.{ext}"
        path.write_text("x")
        assert import_source(tmp_path) == path
        path.unlink()
    assert SOURCE_EXTENSIONS == ("mp3", "wav", "m4a", "flac", "ogg")


def test_tool_registration() -> None:
    assert ANALYZE_MUSIC_TOOL.name == "analyze_music"
    assert ANALYZE_MUSIC_TOOL.stages == {"concept", "produce"}


def test_success_text_picture_and_files(analyzed: tuple[Path, ToolResult, list]) -> None:
    workdir, result, writes = analyzed
    assert not result.is_error, result.text
    for needle in ("BPM", "拟合残差", "置信度", "总时长", "候选"):
        assert needle in result.text
    assert f"BPM {doc_bpm(workdir):g}" in result.text
    assert len(result.images) == 1 and result.images[0].media_type == "image/jpeg"
    assert base64.b64decode(result.images[0].data_base64)[:3] == b"\xff\xd8\xff"
    doc = json.loads((workdir / "music" / "analysis.json").read_text())
    assert doc["bpm"] == pytest.approx(BPM, rel=0.01)
    assert doc["offset"] == pytest.approx(OFFSET, abs=0.03)
    assert (workdir / "music" / "analysis.png").is_file()
    assert sorted(rel for rel, _ in writes) == ["music/analysis.json", "music/analysis.png"]
    for rel, digest in writes:
        assert hashlib.sha256((workdir / rel).read_bytes()).hexdigest() == digest
    assert sorted(p.name for p in (workdir / "music").iterdir()) == [
        "analysis.json",
        "analysis.png",
        "source.wav",
    ]


async def test_repeat_call_gives_identical_products(
    analyzed: tuple[Path, ToolResult, list], project: Path
) -> None:
    workdir, _, _ = analyzed
    result = await invoke_tool(ANALYZE_MUSIC_TOOL, _ctx(project, []), {})
    assert not result.is_error, result.text
    again = await invoke_tool(ANALYZE_MUSIC_TOOL, _ctx(project, []), {})
    assert not again.is_error
    first = (project / "music" / "analysis.json").read_bytes()
    assert (workdir / "music" / "analysis.json").read_bytes() == first
    assert again.text == result.text
    assert (project / "music" / "analysis.json").read_bytes() == first


async def test_no_source_is_a_clear_error(tmp_path: Path) -> None:
    writes: list[tuple[str, str]] = []
    result = await invoke_tool(ANALYZE_MUSIC_TOOL, _ctx(tmp_path, writes), {})
    assert result.is_error and "还没有上传歌曲" in result.text
    assert writes == [] and result.images == []


async def test_silence_is_an_error_and_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / "music").mkdir()
    write_silence(tmp_path / "music" / "source.wav")
    writes: list[tuple[str, str]] = []
    result = await invoke_tool(ANALYZE_MUSIC_TOOL, _ctx(tmp_path, writes), {})
    assert result.is_error and "静音" in result.text
    assert writes == [] and not (tmp_path / "music" / "analysis.json").exists()


async def test_failure_keeps_existing_products(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "music" / "analysis.json").write_text('{"old": true}')
    (project / "music" / "analysis.png").write_bytes(b"old-png")

    async def boom(source: Path, out_dir: Path, *, timeout: float) -> object:
        raise SongJobError("歌曲分析超时")

    monkeypatch.setattr(analyze_module, "run_song_analysis", boom)
    writes: list[tuple[str, str]] = []
    result = await invoke_tool(ANALYZE_MUSIC_TOOL, _ctx(project, writes), {})
    assert result.is_error and "歌曲分析超时" in result.text
    assert writes == []
    assert (project / "music" / "analysis.json").read_text() == '{"old": true}'
    assert (project / "music" / "analysis.png").read_bytes() == b"old-png"


async def test_passes_absolute_resolved_paths(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Path] = {}

    async def spy(source: Path, out_dir: Path, *, timeout: float) -> object:
        seen.update(source=source, out_dir=out_dir)
        raise SongJobError("stop")

    monkeypatch.setattr(analyze_module, "run_song_analysis", spy)
    relative = Path(os.path.relpath(project, Path.cwd()))  # a non-absolute workdir
    await invoke_tool(ANALYZE_MUSIC_TOOL, _ctx(relative, []), {})
    assert seen["source"].is_absolute() and seen["source"] == seen["source"].resolve()
    assert seen["out_dir"].is_absolute() and seen["out_dir"] == seen["out_dir"].resolve()
    assert seen["out_dir"] != project / "music"


async def test_low_confidence_points_to_the_analysis_picture_and_range_json(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = analyze_module.run_song_analysis

    async def lowered(source: Path, out_dir: Path, *, timeout: float) -> object:
        result = await real(source, out_dir, timeout=timeout)
        doc = json.loads(result.analysis_path.read_text())
        doc.update(confidence=0.2, warnings=["拍点分散"])
        result.analysis_path.write_text(json.dumps(doc))
        return result

    monkeypatch.setattr(analyze_module, "run_song_analysis", lowered)
    result = await invoke_tool(ANALYZE_MUSIC_TOOL, _ctx(project, []), {})
    assert not result.is_error
    assert "只是参考" in result.text and "range.json" in result.text
    assert "sections.json" not in result.text and "拍点分散" in result.text


async def test_picture_compression_failure_leaves_products_untouched(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "music" / "analysis.json").write_text('{"old": true}')
    (project / "music" / "analysis.png").write_bytes(b"old-png")

    def boom(png: bytes) -> bytes:
        raise ValueError("cannot compress")

    monkeypatch.setattr(analyze_module, "compress_picture", boom)
    writes: list[tuple[str, str]] = []
    result = await invoke_tool(ANALYZE_MUSIC_TOOL, _ctx(project, writes), {})
    assert result.is_error and "旧产物没有改动" in result.text
    assert writes == []
    assert (project / "music" / "analysis.json").read_text() == '{"old": true}'
    assert (project / "music" / "analysis.png").read_bytes() == b"old-png"
