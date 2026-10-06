"""`MusicStage`：协议值、`prepare_turn`、`finalize_blockers`、状态摘要（子项目 3 设计 §7.1）。"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from studio.agent.stage import StageDefinition, StageRegistry, upstream_of
from studio.stages.beatsheet import STAGE as BEATSHEET
from studio.stages.common.score import tool as music_tool
from studio.stages.common.score.render import render_music_core
from studio.stages.common.score.sources import infer_sources
from studio.stages.concept import STAGE as CONCEPT
from studio.stages.music import STAGE
from studio.stages.pipeline import ProjectKind, build_pipeline
from studio.timeline.load import load_timeline
from studio.workspace.scope import is_writable

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REF = FIXTURES / "synth_music" / "compose_ref.py"
BPM = 128.0


def _beatsheet(bars: int = 3) -> dict[str, Any]:
    return {
        "bpm": BPM,
        "sections": [
            {
                "id": "s1",
                "label": "S1",
                "bars": bars,
                "intent": "x",
                "energy": "low",
                "moments": [],
            },
            {"id": "s2", "label": "S2", "bars": 3, "intent": "x", "energy": "peak", "moments": []},
        ],
    }


def _put_beatsheet(workdir: Path, bars: int = 3) -> None:
    path = workdir / "upstream" / "beatsheet" / "beatsheet.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_beatsheet(bars)), encoding="utf-8")


def test_stage_protocol_values() -> None:
    assert isinstance(STAGE, StageDefinition)
    assert STAGE.name == "music" and STAGE.allow_web is False and STAGE.workspaceless is False
    assert STAGE.reads() == ["concept", "narrative", "beatsheet"]
    assert STAGE.artifact_dirs() == ["music"]
    assert {t.name for t in STAGE.tools()} == {
        "render_music",
        "analyze_music",
        "validate_sections",
        "suggest_upstream_change",
    }


def test_write_scope_allows_only_the_script_and_keeps_products_tool_managed() -> None:
    scope = STAGE.write_scope()
    assert is_writable(scope, "music/compose.py") is True
    for name in ("music.wav", "events.json", "analysis.json", "analysis.png", "render.json"):
        assert is_writable(scope, f"music/{name}") is False
    assert is_writable(scope, "beatsheet/beatsheet.json") is False


def test_upstream_in_both_pipelines() -> None:
    registry = StageRegistry()
    for stage in (CONCEPT, BEATSHEET, STAGE):
        registry.register(stage)
    reel = build_pipeline(ProjectKind("html", False, "synth"))
    assert upstream_of(reel, registry, "music") == ["concept", "beatsheet"]


# ---- prepare_turn ---------------------------------------------------------------------


def test_prepare_turn_writes_the_music_free_timeline_and_the_exemplar(tmp_path: Path) -> None:
    _put_beatsheet(tmp_path)
    STAGE.prepare_turn(tmp_path)
    timeline = json.loads((tmp_path / "upstream" / "timeline.json").read_text())
    assert timeline["music"] is None and timeline["grid"]["bpm"] == BPM
    assert [s["id"] for s in timeline["sections"]] == ["s1", "s2"]
    assert not (tmp_path / "upstream" / "timeline.error.txt").exists()
    exemplar = tmp_path / "upstream" / "exemplar" / "audio-techniques.py"
    assert "STUDIO_OUT_WAV" in exemplar.read_text()


def test_prepare_turn_for_a_narration_project_has_no_grid(tmp_path: Path) -> None:
    target = tmp_path / "upstream" / "narrative"
    target.mkdir(parents=True)
    for name in ("narrative.json", "timing.json"):
        shutil.copyfile(FIXTURES / "animation" / name, target / name)
    STAGE.prepare_turn(tmp_path)
    timeline = json.loads((tmp_path / "upstream" / "timeline.json").read_text())
    assert timeline["grid"] is None and len(timeline["narration"]) == 2


def test_prepare_turn_without_upstream_writes_an_error_instead_of_raising(tmp_path: Path) -> None:
    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "timeline.json").write_text("{}")
    STAGE.prepare_turn(tmp_path)
    assert not (tmp_path / "upstream" / "timeline.json").exists()
    reason = (tmp_path / "upstream" / "timeline.error.txt").read_text()
    assert "beatsheet" in reason and "narrative" in reason


def test_prepare_turn_with_a_broken_beatsheet_writes_the_reason(tmp_path: Path) -> None:
    path = tmp_path / "upstream" / "beatsheet" / "beatsheet.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"bpm": "fast", "sections": []}))
    STAGE.prepare_turn(tmp_path)
    assert "beatsheet" in (tmp_path / "upstream" / "timeline.error.txt").read_text()


# ---- finalize_blockers / status_summary -------------------------------------------------


@pytest.fixture
def rendered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A reel workspace with a successful render, written the way the tool writes it."""
    _put_beatsheet(tmp_path)
    (tmp_path / "music").mkdir()
    shutil.copyfile(REF, tmp_path / "music" / "compose.py")
    loaded = load_timeline(infer_sources(tmp_path, "upstream/", with_music=False))
    outcome = asyncio.run(
        render_music_core(
            tmp_path,
            timeline=loaded.timeline.model_dump(mode="json"),
            base_hash=loaded.base_hash,
            section_energy={},
            wrap_command=lambda argv, env: argv,
        )
    )
    assert outcome.ok, outcome.errors
    return tmp_path


def test_a_fresh_render_can_be_finalised(rendered: Path) -> None:
    assert STAGE.finalize_blockers(rendered) == []


def test_nothing_rendered_yet_blocks(tmp_path: Path) -> None:
    _put_beatsheet(tmp_path)
    blockers = STAGE.finalize_blockers(tmp_path)
    assert blockers and any("render_music" in b for b in blockers)


def test_editing_the_script_after_the_render_blocks(rendered: Path) -> None:
    script = rendered / "music" / "compose.py"
    script.write_text(script.read_text() + "\n# tweak\n")
    assert any("compose.py" in b for b in STAGE.finalize_blockers(rendered))


def test_a_changed_beatsheet_blocks(rendered: Path) -> None:
    _put_beatsheet(rendered, bars=4)
    assert any("节拍脚本" in b or "时间轴" in b for b in STAGE.finalize_blockers(rendered))


def test_a_missing_or_replaced_wav_blocks(rendered: Path) -> None:
    wav = rendered / "music" / "music.wav"
    wav.write_bytes(wav.read_bytes() + b"\0\0")
    assert any("music.wav" in b for b in STAGE.finalize_blockers(rendered))
    wav.unlink()
    assert any("music.wav" in b for b in STAGE.finalize_blockers(rendered))


def test_status_summary_before_and_after_the_render(tmp_path_factory, rendered: Path) -> None:
    assert "未渲染" in STAGE.status_summary(tmp_path_factory.mktemp("empty"))
    summary = STAGE.status_summary(rendered)
    assert "已渲染" in summary and "128" in summary and "11.2" in summary


def test_music_tool_module_is_the_one_the_stage_exposes() -> None:
    assert music_tool.RENDER_MUSIC_TOOL in STAGE.tools()
