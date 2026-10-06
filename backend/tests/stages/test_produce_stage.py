"""`stages.produce`：阶段定义、`prepare_turn`、定稿条件与状态摘要（produce-stage 设计 §5，T4）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from studio.agent.stage import StageDefinition, StageRegistry, upstream_of
from studio.engines.audio.song import file_hash
from studio.stages.common.score.render import render_music_core
from studio.stages.concept import STAGE as CONCEPT
from studio.stages.produce import STAGE
from studio.workspace.scope import is_writable

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FREE = FIXTURES / "synth_music" / "compose_free.py"
DURATION = 16.0
SHOTS: dict[str, Any] = {
    "shots": [
        {"id": "intro", "label": "INTRO", "start": 0.0, "end": 6.0},
        {"id": "drop", "label": "DROP", "start": 6.0, "end": DURATION},
    ]
}


def identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


def _write(root: Path, relpath: str, data: Any) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _scenes(workdir: Path, ids: tuple[str, ...] = ("intro", "drop")) -> None:
    for scene_id in ids:
        target = workdir / "animation" / "scenes" / f"{scene_id}.js"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("module.exports = { draw(ctx, lt, env) {} };\n", encoding="utf-8")


async def _reel(workdir: Path, *, shots: Any = SHOTS, scenes: bool = True) -> None:
    (workdir / "music").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FREE, workdir / "music" / "compose.py")
    outcome = await render_music_core(workdir, wrap_command=identity)
    assert outcome.ok, outcome.errors
    if shots is not None:
        _write(workdir, "animation/shots.json", shots)
    if scenes:
        _scenes(workdir)


def _song(workdir: Path, *, source_hash: str | None = None, duration: float = 40.0) -> None:
    music = workdir / "music"
    music.mkdir(parents=True, exist_ok=True)
    (music / "source.mp3").write_bytes(b"fake-song")
    _write(
        workdir,
        "music/analysis.json",
        {
            "source_hash": source_hash or file_hash(music / "source.mp3"),
            "duration": duration,
            "bpm": 120.0,
            "offset": 0.0,
            "confidence": 0.9,
            "hop": 0.5,
            "energy": [0.3] * int(duration * 2),
            "beats": [0.5 * i for i in range(int(duration * 2))],
            "downbeats": [2.0 * i for i in range(int(duration / 2))],
        },
    )


class TestDefinition:
    def test_satisfies_the_stage_protocol(self) -> None:
        assert isinstance(STAGE, StageDefinition)
        assert STAGE.name == "produce"
        assert STAGE.allow_web is False
        assert STAGE.workspaceless is False

    def test_reads_and_artifact_dirs(self) -> None:
        assert STAGE.reads() == ["concept"]
        assert STAGE.artifact_dirs() == ["music", "animation"]

    def test_upstream_of_the_two_stage_pipeline(self) -> None:
        registry = StageRegistry()
        registry.register(CONCEPT)
        registry.register(STAGE)
        assert upstream_of(["concept", "produce"], registry, "produce") == ["concept"]

    def test_tool_set_is_the_superset_for_both_forms(self) -> None:
        names = {tool.name for tool in STAGE.tools()}
        assert names == {
            "render_music",
            "analyze_music",
            "validate_scenes_html",
            "render_preview_html",
            "suggest_upstream_change",
        }

    @pytest.mark.parametrize(
        ("relpath", "writable"),
        [
            ("music/compose.py", True),
            ("music/range.json", True),
            ("animation/shots.json", True),
            ("animation/scenes/intro.js", True),
            ("animation/lib/palette.js", True),
            ("animation/global.js", True),
            ("animation/assets/logo.svg", True),
            ("music/music.wav", False),
            ("music/events.json", False),
            ("music/analysis.json", False),
            ("music/analysis.png", False),
            ("music/render.json", False),
            ("music/source.mp3", False),
            ("music/sections.json", False),
            ("animation/other.js", False),
            ("concept/brief.md", False),
            ("beatsheet/beatsheet.json", False),
        ],
    )
    def test_write_scope(self, relpath: str, writable: bool) -> None:
        assert is_writable(STAGE.write_scope(), relpath) is writable


class TestPrepareTurn:
    def test_copies_both_exemplars_and_writes_no_timeline(self, tmp_path: Path) -> None:
        STAGE.prepare_turn(tmp_path)
        exemplars = tmp_path / "upstream" / "exemplar"
        assert (exemplars / "audio-techniques.py").is_file()
        assert (exemplars / "canvas-techniques.js").is_file()
        assert not (tmp_path / "upstream" / "timeline.json").exists()
        assert not (tmp_path / "upstream" / "timeline.error.txt").exists()

    def test_is_idempotent(self, tmp_path: Path) -> None:
        STAGE.prepare_turn(tmp_path)
        STAGE.prepare_turn(tmp_path)
        assert (tmp_path / "upstream" / "exemplar" / "audio-techniques.py").is_file()


class TestFinalizeBlockersReel:
    async def test_a_complete_reel_can_be_finalized(self, tmp_path: Path) -> None:
        await _reel(tmp_path)
        assert STAGE.finalize_blockers(tmp_path) == []

    def test_nothing_done_yet_lists_what_is_missing(self, tmp_path: Path) -> None:
        blockers = STAGE.finalize_blockers(tmp_path)
        assert any("render_music" in b for b in blockers)
        assert any("animation/shots.json" in b for b in blockers)

    async def test_script_edited_after_rendering(self, tmp_path: Path) -> None:
        await _reel(tmp_path)
        script = tmp_path / "music" / "compose.py"
        script.write_text(script.read_text(encoding="utf-8") + "\n# tweak\n", encoding="utf-8")
        blockers = STAGE.finalize_blockers(tmp_path)
        assert any("compose.py" in b and "render_music" in b for b in blockers)

    async def test_wav_replaced_after_rendering(self, tmp_path: Path) -> None:
        await _reel(tmp_path)
        wav = tmp_path / "music" / "music.wav"
        wav.write_bytes(wav.read_bytes()[:-2000])
        blockers = STAGE.finalize_blockers(tmp_path)
        assert any("music.wav" in b and "render_music" in b for b in blockers)

    async def test_missing_wav(self, tmp_path: Path) -> None:
        await _reel(tmp_path)
        (tmp_path / "music" / "music.wav").unlink()
        assert any("music.wav" in b for b in STAGE.finalize_blockers(tmp_path))

    async def test_missing_shots_file(self, tmp_path: Path) -> None:
        await _reel(tmp_path, shots=None)
        blockers = STAGE.finalize_blockers(tmp_path)
        assert any("animation/shots.json" in b for b in blockers)

    async def test_shots_that_do_not_cover_the_audio_name_both_lengths(
        self, tmp_path: Path
    ) -> None:
        short = {
            "shots": [{"id": "intro", "start": 0, "end": 6}, {"id": "drop", "start": 6, "end": 10}]
        }
        await _reel(tmp_path, shots=short)
        text = "\n".join(STAGE.finalize_blockers(tmp_path))
        assert "16" in text and "10" in text

    async def test_a_shot_without_a_scene_file(self, tmp_path: Path) -> None:
        await _reel(tmp_path, scenes=False)
        _scenes(tmp_path, ("intro",))
        blockers = STAGE.finalize_blockers(tmp_path)
        assert any("animation/scenes/drop.js" in b for b in blockers)
        assert not any("scenes/intro.js" in b for b in blockers)

    async def test_an_empty_scene_file_counts_as_missing(self, tmp_path: Path) -> None:
        await _reel(tmp_path)
        (tmp_path / "animation" / "scenes" / "drop.js").write_text("  \n", encoding="utf-8")
        assert any("scenes/drop.js" in b for b in STAGE.finalize_blockers(tmp_path))

    async def test_blockers_do_not_repeat_the_same_music_problem(self, tmp_path: Path) -> None:
        (tmp_path / "animation").mkdir()
        _write(tmp_path, "animation/shots.json", SHOTS)
        _scenes(tmp_path)
        blockers = STAGE.finalize_blockers(tmp_path)
        assert sum("render_music" in b for b in blockers) == 1


class TestFinalizeBlockersSong:
    def test_a_complete_song_project_can_be_finalized(self, tmp_path: Path) -> None:
        _song(tmp_path)
        _write(tmp_path, "animation/shots.json", {"shots": [{"id": "all", "start": 0, "end": 40}]})
        _scenes(tmp_path, ("all",))
        assert STAGE.finalize_blockers(tmp_path) == []

    def test_a_range_narrows_the_required_shot_length(self, tmp_path: Path) -> None:
        _song(tmp_path)
        _write(tmp_path, "music/range.json", {"start": 10, "end": 22})
        _write(tmp_path, "animation/shots.json", {"shots": [{"id": "all", "start": 0, "end": 12}]})
        _scenes(tmp_path, ("all",))
        assert STAGE.finalize_blockers(tmp_path) == []

    def test_not_analyzed_yet(self, tmp_path: Path) -> None:
        (tmp_path / "music").mkdir()
        (tmp_path / "music" / "source.mp3").write_bytes(b"x")
        assert any("analyze_music" in b for b in STAGE.finalize_blockers(tmp_path))

    def test_analysis_of_another_file(self, tmp_path: Path) -> None:
        _song(tmp_path, source_hash="deadbeef")
        assert any("analyze_music" in b for b in STAGE.finalize_blockers(tmp_path))

    def test_invalid_range_is_a_blocker(self, tmp_path: Path) -> None:
        _song(tmp_path)
        _write(tmp_path, "music/range.json", {"start": 30, "end": 80})
        _write(tmp_path, "animation/shots.json", {"shots": [{"id": "all", "start": 0, "end": 40}]})
        _scenes(tmp_path, ("all",))
        assert any("range.json" in b for b in STAGE.finalize_blockers(tmp_path))

    def test_old_sections_json_is_ignored(self, tmp_path: Path) -> None:
        _song(tmp_path)
        _write(tmp_path, "music/sections.json", {"sections": []})
        _write(tmp_path, "animation/shots.json", {"shots": [{"id": "all", "start": 0, "end": 40}]})
        _scenes(tmp_path, ("all",))
        assert STAGE.finalize_blockers(tmp_path) == []


class TestStatusSummary:
    def test_before_anything(self, tmp_path: Path) -> None:
        text = STAGE.status_summary(tmp_path)
        assert "未渲染" in text and "镜头" in text

    async def test_rendered_reel(self, tmp_path: Path) -> None:
        await _reel(tmp_path)
        text = STAGE.status_summary(tmp_path)
        assert "16.00" in text and "个事件" in text and "2 个镜头" in text and "120" in text

    def test_analyzed_song(self, tmp_path: Path) -> None:
        _song(tmp_path)
        _write(tmp_path, "animation/shots.json", {"shots": [{"id": "all", "start": 0, "end": 40}]})
        text = STAGE.status_summary(tmp_path)
        assert "已分析" in text and "40.00" in text and "1 个镜头" in text

    def test_unanalyzed_song(self, tmp_path: Path) -> None:
        (tmp_path / "music").mkdir()
        (tmp_path / "music" / "source.mp3").write_bytes(b"x")
        assert "未分析" in STAGE.status_summary(tmp_path)

    def test_broken_shots_file_does_not_crash_the_summary(self, tmp_path: Path) -> None:
        (tmp_path / "animation").mkdir()
        (tmp_path / "animation" / "shots.json").write_text("{not json", encoding="utf-8")
        assert "shots.json" in STAGE.status_summary(tmp_path)
