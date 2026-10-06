"""`render_music` and `analyze_music` as used from the `produce` stage (plan T3)."""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import pytest

from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.music import analyze as analyze_module
from studio.stages.music import tool as music_tool
from studio.stages.music.analyze import ANALYZE_MUSIC_TOOL, NO_SOURCE_PRODUCE_MESSAGE
from studio.stages.music.tool import RENDER_MUSIC_TOOL

FREE = Path(__file__).resolve().parents[1] / "fixtures" / "synth_music" / "compose_free.py"


def identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


def _ctx(workdir: Path, writes: list[tuple[str, str]], stage: str = "produce") -> ToolContext:
    return ToolContext(
        project_id="p",
        stage=stage,
        workdir=workdir,
        record_tool_write=lambda rel, digest: writes.append((rel, digest)),
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A produce workspace: a script and nothing else — no upstream timeline, no beat sheet."""
    monkeypatch.setattr(music_tool, "sandbox_wrapper", lambda workdir: identity)
    (tmp_path / "music").mkdir()
    shutil.copyfile(FREE, tmp_path / "music" / "compose.py")
    return tmp_path


async def test_render_music_needs_no_upstream_in_the_produce_stage(project: Path) -> None:
    writes: list[tuple[str, str]] = []
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(project, writes), {})
    assert not result.is_error, result.text
    assert "BPM 120" in result.text and "重定时" not in result.text
    assert len(writes) == 5 and (project / "music" / "music.wav").is_file()
    assert not (project / "upstream").exists()


async def test_render_music_text_says_when_bpm_is_not_declared(project: Path) -> None:
    script = project / "music" / "compose.py"
    script.write_text(
        script.read_text(encoding="utf-8").replace('document["bpm"] = BPM', "pass"),
        encoding="utf-8",
    )
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(project, []), {})
    assert not result.is_error, result.text
    assert "未声明 BPM" in result.text and "没有网格可对齐" in result.text


async def test_render_music_picture_stays_within_the_shared_budget(project: Path) -> None:
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(project, []), {})
    assert len(result.images) == 1
    assert len(base64.b64decode(result.images[0].data_base64)) <= 300_000


async def test_render_music_refuses_a_song_project_with_the_produce_hint(project: Path) -> None:
    (project / "music" / "source.mp3").write_bytes(b"x")
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(project, []), {})
    assert result.is_error
    assert "analyze_music" in result.text and "range.json" in result.text
    assert "sections.json" not in result.text


async def test_render_music_in_the_music_stage_still_needs_the_timeline(project: Path) -> None:
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(project, [], stage="music"), {})
    assert result.is_error and "时间轴不可用" in result.text


async def test_analyze_music_without_a_song_asks_for_an_upload(tmp_path: Path) -> None:
    for stage in ("concept", "produce"):
        result = await invoke_tool(ANALYZE_MUSIC_TOOL, _ctx(tmp_path, [], stage=stage), {})
        assert result.is_error and result.text == NO_SOURCE_PRODUCE_MESSAGE


def test_analysis_summary_points_to_range_json_not_sections_json() -> None:
    doc = {
        "bpm": 120.0,
        "offset": 0.4,
        "duration": 60.0,
        "residual_ms": 80.0,
        "confidence": 0.2,
        "candidates": [8.0, 16.0],
        "warnings": [],
    }
    produce = analyze_module._summary(doc, produce=True)
    assert "range.json" in produce and "sections.json" not in produce
    legacy = analyze_module._summary(doc)
    assert "sections.json" in legacy
    json.dumps(doc)  # the doc stays plain data


async def test_hundreds_of_events_stay_a_short_summary(project: Path) -> None:
    """The real session had 607 events: the tool text lists counts and a few names, not them all."""
    script = project / "music" / "compose.py"
    patch = (
        "document['events'] += [{'name': 'tick%d' % (i % 40), 'kind': 'onset',"
        " 'start': 0.1 + i * 0.025, 'end': 0.12 + i * 0.025} for i in range(600)]\n"
    )
    marker = "    json.dump(document, handle)"
    source = script.read_text(encoding="utf-8")
    script.write_text(source.replace(marker, "    " + patch + marker), encoding="utf-8")
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(project, []), {})
    assert not result.is_error, result.text
    assert "649 个事件" in result.text
    assert len(result.text.encode("utf-8")) < 6_000
