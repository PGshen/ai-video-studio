"""`MusicStage`（讲解 + 背景乐）：协议值、`prepare_turn`、`finalize_blockers`、状态摘要。"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from studio.agent.stage import StageDefinition, StageRegistry, upstream_of
from studio.stages.common.score import tool as music_tool
from studio.stages.common.score.render import render_music_core
from studio.stages.common.score.sources import infer_sources
from studio.stages.music import STAGE
from studio.stages.narrative import STAGE as NARRATIVE
from studio.stages.pipeline import ProjectKind, build_pipeline
from studio.timeline.load import load_timeline
from studio.workspace.scope import is_writable

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REF = FIXTURES / "synth_music" / "compose_ref.py"


def _put_narrative(workdir: Path) -> None:
    target = workdir / "upstream" / "narrative"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("narrative.json", "timing.json"):
        shutil.copyfile(FIXTURES / "animation" / name, target / name)


def test_stage_protocol_values() -> None:
    assert isinstance(STAGE, StageDefinition)
    assert STAGE.name == "music" and STAGE.allow_web is False and STAGE.workspaceless is False
    assert STAGE.reads() == ["narrative"]
    assert STAGE.artifact_dirs() == ["music"]
    assert {t.name for t in STAGE.tools()} == {"render_music", "suggest_upstream_change"}


def test_write_scope_allows_only_the_script_and_keeps_products_tool_managed() -> None:
    scope = STAGE.write_scope()
    assert is_writable(scope, "music/compose.py") is True
    for name in ("music.wav", "events.json", "analysis.json", "analysis.png", "render.json"):
        assert is_writable(scope, f"music/{name}") is False
    for relpath in ("music/range.json", "music/sections.json", "animation/shots.json"):
        assert is_writable(scope, relpath) is False


def test_upstream_in_the_explainer_pipeline() -> None:
    registry = StageRegistry()
    for stage in (NARRATIVE, STAGE):
        registry.register(stage)
    pipeline = build_pipeline(ProjectKind("html", True, "synth"))
    assert upstream_of(pipeline, registry, "music") == ["narrative"]


# ---- prepare_turn ---------------------------------------------------------------------


def test_prepare_turn_writes_the_music_free_timeline_and_the_exemplar(tmp_path: Path) -> None:
    _put_narrative(tmp_path)
    STAGE.prepare_turn(tmp_path)
    timeline = json.loads((tmp_path / "upstream" / "timeline.json").read_text())
    assert timeline["music"] is None and timeline["grid"] is None
    assert len(timeline["narration"]) == 2
    assert not (tmp_path / "upstream" / "timeline.error.txt").exists()
    exemplar = tmp_path / "upstream" / "exemplar" / "audio-techniques.py"
    assert "STUDIO_OUT_WAV" in exemplar.read_text()


def test_prepare_turn_without_upstream_writes_an_error_instead_of_raising(tmp_path: Path) -> None:
    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "timeline.json").write_text("{}")
    STAGE.prepare_turn(tmp_path)
    assert not (tmp_path / "upstream" / "timeline.json").exists()
    reason = (tmp_path / "upstream" / "timeline.error.txt").read_text()
    assert "narrative" in reason and "beatsheet" not in reason


def test_prepare_turn_with_a_broken_narrative_writes_the_reason(tmp_path: Path) -> None:
    target = tmp_path / "upstream" / "narrative"
    target.mkdir(parents=True)
    (target / "narrative.json").write_text("{not json")
    (target / "timing.json").write_text("{}")
    STAGE.prepare_turn(tmp_path)
    assert (tmp_path / "upstream" / "timeline.error.txt").read_text().strip()


# ---- finalize_blockers / status_summary -------------------------------------------------


@pytest.fixture
def rendered(tmp_path: Path) -> Path:
    """An explainer workspace with a successful render, written the way the tool writes it."""
    _put_narrative(tmp_path)
    (tmp_path / "music").mkdir()
    shutil.copyfile(REF, tmp_path / "music" / "compose.py")
    loaded = load_timeline(infer_sources(tmp_path, "upstream/", with_music=False))
    outcome = asyncio.run(
        render_music_core(
            tmp_path,
            timeline=loaded.timeline.model_dump(mode="json"),
            base_hash=loaded.base_hash,
            wrap_command=lambda argv, env: argv,
        )
    )
    assert outcome.ok, outcome.errors
    return tmp_path


def test_a_fresh_render_can_be_finalised(rendered: Path) -> None:
    assert STAGE.finalize_blockers(rendered) == []


def test_nothing_rendered_yet_blocks(tmp_path: Path) -> None:
    _put_narrative(tmp_path)
    blockers = STAGE.finalize_blockers(tmp_path)
    assert blockers and any("render_music" in b for b in blockers)


def test_editing_the_script_after_the_render_blocks(rendered: Path) -> None:
    script = rendered / "music" / "compose.py"
    script.write_text(script.read_text() + "\n# tweak\n")
    assert any("compose.py" in b for b in STAGE.finalize_blockers(rendered))


def test_a_changed_narrative_blocks(rendered: Path) -> None:
    timing = rendered / "upstream" / "narrative" / "timing.json"
    doc = json.loads(timing.read_text())
    doc["scenes"][0]["duration_seconds"] = float(doc["scenes"][0]["duration_seconds"]) + 2.0
    timing.write_text(json.dumps(doc))
    assert any("时间轴" in b or "叙事" in b for b in STAGE.finalize_blockers(rendered))


def test_a_missing_or_replaced_wav_blocks(rendered: Path) -> None:
    wav = rendered / "music" / "music.wav"
    wav.write_bytes(wav.read_bytes() + b"\0\0")
    assert any("music.wav" in b for b in STAGE.finalize_blockers(rendered))
    wav.unlink()
    assert any("music.wav" in b for b in STAGE.finalize_blockers(rendered))


def test_status_summary_before_and_after_the_render(tmp_path_factory, rendered: Path) -> None:
    assert "未渲染" in STAGE.status_summary(tmp_path_factory.mktemp("empty"))
    summary = STAGE.status_summary(rendered)
    assert "已渲染" in summary and "100" in summary


def test_music_tool_module_is_the_one_the_stage_exposes() -> None:
    assert music_tool.RENDER_MUSIC_TOOL in STAGE.tools()
