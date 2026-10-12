"""`stages.free_explainer`：自由讲解的单阶段（free-mode 设计 §4，计划 T6）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from studio.agent.stage import StageDefinition
from studio.api.animation_stage import animation_stage_of
from studio.stages.common.score.render import render_music_core
from studio.stages.common.timeline_source import load_live_narrated
from studio.stages.free_explainer import STAGE
from studio.stages.pipeline import ProjectKind, kind_settings
from studio.workspace.scope import is_writable

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REF = FIXTURES / "synth_music" / "compose_ref.py"


def identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


def _narration(workdir: Path) -> None:
    target = workdir / "narrative"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("narrative.json", "timing.json"):
        shutil.copyfile(FIXTURES / "animation" / name, target / name)


def _scene(workdir: Path, scene_id: str) -> None:
    path = workdir / "animation" / "scenes" / f"{scene_id}.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("module.exports = { draw(ctx, lt, env) {} };\n", encoding="utf-8")


def test_satisfies_the_stage_protocol() -> None:
    assert isinstance(STAGE, StageDefinition)
    assert STAGE.name == "free_explainer"
    assert STAGE.allow_web is True
    assert STAGE.workspaceless is False
    assert STAGE.reads() == []
    assert STAGE.artifact_dirs() == ["narrative", "music", "animation"]


def test_tools() -> None:
    assert {tool.name for tool in STAGE.tools()} == {
        "web_search",
        "fetch_url",
        "validate_narrative",
        "synthesize_tts",
        "render_music",
        "validate_scenes_html",
        "render_preview_html",
    }


@pytest.mark.parametrize(
    "path", ["narrative/narrative.json", "notes/outline.md", "animation/scenes/s-hook.js", "x.md"]
)
def test_the_whole_workspace_is_writable(path: str) -> None:
    assert is_writable(STAGE.write_scope(), path)


@pytest.mark.parametrize(
    "path",
    [
        "narrative/timing.json",
        "narrative/audio/s-hook.mp3",
        "style/STYLE.md",
        "music/render.json",
        "uploads/a.pdf",
    ],
)
def test_voice_music_style_and_uploads_are_not_writable(path: str) -> None:
    assert not is_writable(STAGE.write_scope(), path)


def test_finalize_has_no_extra_blockers(tmp_path: Path) -> None:
    # D1: rendering is the gate; the worker's pre-checks name what is missing.
    assert STAGE.finalize_blockers(tmp_path) == []


def test_prepare_turn_copies_scene_exemplars_only(tmp_path: Path) -> None:
    STAGE.prepare_turn(tmp_path)

    names = sorted(p.name for p in (tmp_path / "upstream" / "exemplar").iterdir())
    assert names == ["canvas-techniques.js", "webgl-techniques.js"]
    assert not (tmp_path / "upstream" / "timeline.json").exists()


def test_prepare_turn_adds_the_audio_exemplar_with_background_music(tmp_path: Path) -> None:
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "compose.py").write_text("", encoding="utf-8")

    STAGE.prepare_turn(tmp_path)

    assert (tmp_path / "upstream" / "exemplar" / "audio-techniques.py").is_file()


def test_status_summary_on_an_empty_workspace(tmp_path: Path) -> None:
    summary = STAGE.status_summary(tmp_path)

    assert "还没有 narrative/narrative.json" in summary


def test_status_summary_with_narration_and_partial_scenes(tmp_path: Path) -> None:
    _narration(tmp_path)
    _scene(tmp_path, "s-hook")

    summary = STAGE.status_summary(tmp_path)

    assert "2 个镜头" in summary
    assert "配音与叙事一致" in summary
    assert "场景 1/2" in summary
    assert "s-explain" in summary


def test_status_summary_flags_narration_edited_after_voicing(tmp_path: Path) -> None:
    _narration(tmp_path)
    path = tmp_path / "narrative" / "narrative.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["scenes"].append({**doc["scenes"][-1], "id": "s-new"})
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    summary = STAGE.status_summary(tmp_path)

    assert "需要重新配音" in summary
    assert "s-new" in summary


async def test_status_summary_flags_stale_background_music(tmp_path: Path) -> None:
    _narration(tmp_path)
    (tmp_path / "music").mkdir()
    shutil.copyfile(REF, tmp_path / "music" / "compose.py")
    base = load_live_narrated(tmp_path, with_music=False)
    outcome = await render_music_core(
        tmp_path,
        timeline=base.timeline.model_dump(mode="json"),
        base_hash=base.base_hash,
        wrap_command=identity,
    )
    assert outcome.ok, outcome.errors
    assert "配乐与当前时间轴一致" in STAGE.status_summary(tmp_path)

    timing = tmp_path / "narrative" / "timing.json"
    doc = json.loads(timing.read_text(encoding="utf-8"))
    first = doc["scenes"][0]
    first["duration_seconds"] = float(first["duration_seconds"]) + 1.0
    timing.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    assert "配乐过期" in STAGE.status_summary(tmp_path)


def test_prompt_is_free_mode_and_carries_the_contracts() -> None:
    prompt = STAGE.system_prompt()

    assert prompt.startswith("# 自由讲解")
    for anchor in (
        "照用户说的做",
        "### beats 的四个字段",
        "synthesize_tts",
        "## env 契约",
        "STUDIO_TIMELINE",
        ".js",
    ):
        assert anchor in prompt, anchor
    assert "upstream/topic" not in prompt
    assert "suggest_upstream_change" not in prompt


@pytest.mark.parametrize(
    "kind", [ProjectKind("html", True, "none", "free"), ProjectKind("html", True, "synth", "free")]
)
def test_free_explainer_is_the_animation_stage(kind: ProjectKind) -> None:
    assert animation_stage_of(kind_settings(kind)) == "free_explainer"
