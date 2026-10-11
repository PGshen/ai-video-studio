"""`stages.free_produce`：自由短片与自由 MV 的单阶段（free-mode 设计 §4，计划 T5）。"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from studio.agent.stage import StageDefinition
from studio.api.animation_stage import animation_stage_of
from studio.stages.free_produce import STAGE
from studio.stages.pipeline import MusicSource, ProjectKind, kind_settings
from studio.workspace.scope import is_writable


def test_satisfies_the_stage_protocol() -> None:
    assert isinstance(STAGE, StageDefinition)
    assert STAGE.name == "free_produce"
    assert STAGE.allow_web is True
    assert STAGE.workspaceless is False
    assert STAGE.reads() == []
    assert STAGE.artifact_dirs() == ["music", "animation"]


def test_tools() -> None:
    assert {tool.name for tool in STAGE.tools()} == {
        "web_search",
        "fetch_url",
        "render_music",
        "analyze_music",
        "validate_scenes_html",
        "render_preview_html",
    }


@pytest.mark.parametrize(
    "path",
    [
        "notes/a.md",
        "animation/scenes/s1.js",
        "animation/shots.json",
        "music/compose.py",
        "foo/bar.md",
    ],
)
def test_the_whole_workspace_is_writable(path: str) -> None:
    assert is_writable(STAGE.write_scope(), path)


@pytest.mark.parametrize(
    "path",
    [
        "style/STYLE.md",
        "style/exemplars/a.md",
        "music/music.wav",
        "music/events.json",
        "music/analysis.json",
        "music/analysis.png",
        "music/render.json",
        "music/source.mp3",
        "music/lyrics.lrc",
        "uploads/x.png",
    ],
)
def test_style_tool_outputs_and_uploads_are_not_writable(path: str) -> None:
    assert not is_writable(STAGE.write_scope(), path)


def test_prepare_turn_only_copies_exemplars(tmp_path: Path) -> None:
    STAGE.prepare_turn(tmp_path)

    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert written
    assert all(path.startswith("upstream/exemplar/") for path in written)
    assert not (tmp_path / "upstream" / "timeline.json").exists()


def test_status_summary_without_music_points_at_both_forms(tmp_path: Path) -> None:
    summary = STAGE.status_summary(tmp_path)

    assert "render_music" in summary
    assert "上传歌曲" in summary


def test_prompt_is_free_mode_and_carries_the_contracts() -> None:
    prompt = STAGE.system_prompt()

    assert prompt.startswith("# 自由创作")
    for anchor in ("照用户说的做", "notes/", "STUDIO_OUT_EVENTS", "music/range.json", "env.lyric"):
        assert anchor in prompt, anchor
    assert "upstream/concept" not in prompt
    assert "suggest_upstream_change" not in prompt


@pytest.mark.parametrize("music_source", ["synth", "import"])
def test_free_produce_is_the_animation_stage(music_source: str) -> None:
    kind = ProjectKind("html", False, cast(MusicSource, music_source), "free")
    settings = kind_settings(kind)
    assert animation_stage_of(settings) == "free_produce"
