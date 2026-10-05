"""`MusicStage` import form (4A T6): tool set, write scope, finalize, status, prepare_turn.

The stage cannot see project settings, so the import form is recognised by the presence of
`music/source.<ext>` in the workspace (design §6.1).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.music import STAGE
from studio.stages.music.sources import SOURCE_EXTENSIONS
from studio.stages.music.tool import RENDER_MUSIC_TOOL
from studio.stages.music.validate_sections import VALIDATE_SECTIONS_TOOL
from studio.workspace.scope import is_writable

SOURCE_BYTES = b"not really audio, only hashed"


def _analysis(source_hash: str) -> dict[str, Any]:
    # 120 BPM, first downbeat at 0.5 s: downbeats at 0.5, 2.5, 4.5, ... (a bar is 2 s)
    return {
        "source_hash": source_hash,
        "duration": 40.0,
        "bpm": 120.0,
        "offset": 0.5,
        "hop": 0.1,
        "energy": [0.5] * 400,
        "residual_ms": 5.0,
        "confidence": 0.9,
    }


SECTIONS: dict[str, Any] = {
    "sections": [
        {"id": "intro", "label": "Intro", "start": 0.5, "end": 8.5},
        {"id": "verse", "label": "Verse", "start": 8.5, "end": 24.5},
    ]
}


def _put_source(workdir: Path, ext: str = "mp3", data: bytes = SOURCE_BYTES) -> Path:
    path = workdir / "music" / f"source.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _put_analysis(workdir: Path, source_hash: str | None = None) -> None:
    digest = source_hash or hashlib.sha256(SOURCE_BYTES).hexdigest()
    (workdir / "music" / "analysis.json").write_text(json.dumps(_analysis(digest)))


def _put_sections(workdir: Path, doc: dict[str, Any] | None = None) -> None:
    (workdir / "music" / "sections.json").write_text(json.dumps(doc or SECTIONS))


@pytest.fixture
def analysed(tmp_path: Path) -> Path:
    _put_source(tmp_path)
    _put_analysis(tmp_path)
    _put_sections(tmp_path)
    return tmp_path


def _ctx(workdir: Path) -> ToolContext:
    return ToolContext(
        project_id="p", stage="music", workdir=workdir, record_tool_write=lambda rel, digest: None
    )


# ---- protocol values ---------------------------------------------------------------------


def test_tools_are_a_fixed_superset_and_reads_are_unchanged() -> None:
    assert {t.name for t in STAGE.tools()} == {
        "render_music",
        "analyze_music",
        "validate_sections",
        "suggest_upstream_change",
    }
    assert STAGE.reads() == ["concept", "narrative", "beatsheet"]


def test_write_scope_allows_sections_and_keeps_the_source_tool_managed() -> None:
    scope = STAGE.write_scope()
    assert is_writable(scope, "music/sections.json") is True
    for ext in SOURCE_EXTENSIONS:
        assert is_writable(scope, f"music/source.{ext}") is False
    assert is_writable(scope, "music/analysis.json") is False
    assert is_writable(scope, "music/analysis.png") is False
    assert is_writable(scope, "music/compose.py") is True  # synth form unchanged


# ---- finalize_blockers -------------------------------------------------------------------


def test_no_source_and_no_render_gives_a_neutral_blocker(tmp_path: Path) -> None:
    assert STAGE.finalize_blockers(tmp_path) == [
        "还没有配乐：合成形态请写 music/compose.py 并 render_music；导入形态请先上传歌曲"
    ]


def test_source_not_yet_analysed_blocks(tmp_path: Path) -> None:
    _put_source(tmp_path)
    blockers = STAGE.finalize_blockers(tmp_path)
    assert any("analyze_music" in b for b in blockers)
    assert not any("render_music" in b for b in blockers)


def test_replaced_source_blocks(analysed: Path) -> None:
    _put_source(analysed, data=SOURCE_BYTES + b"!")
    assert "源文件已更换，需要重新 analyze_music" in STAGE.finalize_blockers(analysed)


@pytest.mark.parametrize("ext", ["wav", "flac"])
def test_any_whitelisted_extension_counts_as_the_import_form(tmp_path: Path, ext: str) -> None:
    _put_source(tmp_path, ext=ext)
    _put_analysis(tmp_path)
    _put_sections(tmp_path)
    assert STAGE.finalize_blockers(tmp_path) == []


def test_unreadable_analysis_blocks(analysed: Path) -> None:
    (analysed / "music" / "analysis.json").write_text("{not json")
    assert any("analyze_music" in b for b in STAGE.finalize_blockers(analysed))


def test_missing_sections_blocks(analysed: Path) -> None:
    (analysed / "music" / "sections.json").unlink()
    assert any("sections.json" in b for b in STAGE.finalize_blockers(analysed))


def test_each_sections_error_is_its_own_blocker(analysed: Path) -> None:
    doc = json.loads(json.dumps(SECTIONS))
    doc["sections"][1]["start"] = 10.5  # gap after intro
    doc["sections"][1]["end"] = 25.0  # off the downbeat grid
    _put_sections(analysed, doc)
    blockers = STAGE.finalize_blockers(analysed)
    assert len(blockers) >= 2
    assert any("空隙" in b for b in blockers)
    assert any("强拍" in b for b in blockers)


def test_a_valid_import_workspace_can_be_finalised(analysed: Path) -> None:
    assert STAGE.finalize_blockers(analysed) == []


# ---- status_summary ----------------------------------------------------------------------


def test_status_when_not_analysed(tmp_path: Path) -> None:
    _put_source(tmp_path)
    assert STAGE.status_summary(tmp_path) == "未分析"


def test_status_when_analysed_without_sections(tmp_path: Path) -> None:
    _put_source(tmp_path)
    _put_analysis(tmp_path)
    assert STAGE.status_summary(tmp_path) == "已分析，待写 sections.json"


def test_status_when_analysed_with_sections(analysed: Path) -> None:
    assert STAGE.status_summary(analysed) == "已分析：BPM 120，40.00 秒，置信度 0.90；2 个段落"


# ---- prepare_turn ------------------------------------------------------------------------


def test_prepare_turn_in_the_import_form_writes_no_timeline_and_clears_old_ones(
    tmp_path: Path,
) -> None:
    _put_source(tmp_path)
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "timeline.json").write_text("{}")
    (upstream / "timeline.error.txt").write_text("old\n")
    STAGE.prepare_turn(tmp_path)
    assert not (upstream / "timeline.json").exists()
    assert not (upstream / "timeline.error.txt").exists()
    assert not (upstream / "exemplar").exists()


def test_prepare_turn_without_upstream_mentions_the_mv_upload(tmp_path: Path) -> None:
    STAGE.prepare_turn(tmp_path)
    reason = (tmp_path / "upstream" / "timeline.error.txt").read_text()
    assert "音乐 MV 请先上传歌曲" in reason


# ---- tools in the wrong form ------------------------------------------------------------


async def test_render_music_refuses_the_import_form(tmp_path: Path) -> None:
    _put_source(tmp_path)
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(tmp_path), {})
    assert result.is_error and "导入形态不用合成脚本" in result.text


async def test_validate_sections_refuses_without_a_source(tmp_path: Path) -> None:
    result = await invoke_tool(VALIDATE_SECTIONS_TOOL, _ctx(tmp_path), {})
    assert result.is_error and "还没有上传音乐" in result.text
