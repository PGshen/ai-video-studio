"""`stages.animation_html`：阶段定义与 `prepare_turn`（子项目 2 设计 §6.1、§6.2）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from studio.agent.stage import StageDefinition, StageRegistry, upstream_of
from studio.stages.animation_html import STAGE
from studio.timeline import TimelineLayers, build_timeline, narration_from_documents
from studio.workspace.scope import is_writable

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "animation"


def _upstream(workdir: Path) -> None:
    target = workdir / "upstream" / "narrative"
    target.mkdir(parents=True)
    for name in ("narrative.json", "timing.json"):
        shutil.copyfile(FIXTURES / name, target / name)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestDefinition:
    def test_satisfies_the_stage_protocol(self) -> None:
        assert isinstance(STAGE, StageDefinition)
        assert STAGE.name == "animation_html"
        assert STAGE.allow_web is False
        assert STAGE.workspaceless is False

    def test_reads_and_artifact_dirs(self) -> None:
        assert STAGE.reads() == ["narrative", "beatsheet", "music"]
        assert STAGE.artifact_dirs() == ["animation"]
        assert STAGE.finalize_blockers(Path("/nonexistent")) == []

    @pytest.mark.parametrize(
        ("relpath", "writable"),
        [
            ("animation/scenes/s-hook.js", True),
            ("animation/lib/palette.js", True),
            ("animation/global.js", True),
            ("animation/assets/logo.svg", True),
            ("animation/scenes/s-hook.py", False),
            ("animation/other.js", False),
            ("upstream/timeline.json", False),
            ("upstream/exemplar/canvas-techniques.js", False),
            ("narrative/narrative.json", False),
            ("style/STYLE.md", False),
        ],
    )
    def test_write_scope(self, relpath: str, writable: bool) -> None:
        assert is_writable(STAGE.write_scope(), relpath) is writable

    def test_upstream_of_in_an_explainer_pipeline_is_narrative_only(self) -> None:
        registry = StageRegistry()
        registry.register(STAGE)
        pipeline = ["topic", "narrative", "animation_html"]
        assert upstream_of(pipeline, registry, "animation_html") == ["narrative"]

    def test_status_summary_counts_scenes_against_the_timeline(self, tmp_path: Path) -> None:
        _upstream(tmp_path)
        STAGE.prepare_turn(tmp_path)
        scenes = tmp_path / "animation" / "scenes"
        scenes.mkdir(parents=True)
        (scenes / "s-hook.js").write_text("module.exports = {};", encoding="utf-8")
        assert STAGE.status_summary(tmp_path) == "scenes/ 下已写 1 个镜头 / 时间轴共 2 个镜头"

    def test_status_summary_without_timeline(self, tmp_path: Path) -> None:
        assert STAGE.status_summary(tmp_path) == "scenes/ 下已写 0 个镜头 / 时间轴共 未知 个镜头"


class TestPrepareTurn:
    def test_writes_timeline_and_exemplar(self, tmp_path: Path) -> None:
        _upstream(tmp_path)
        STAGE.prepare_turn(tmp_path)
        narrative = _load(tmp_path / "upstream" / "narrative" / "narrative.json")
        timing = _load(tmp_path / "upstream" / "narrative" / "timing.json")
        expected = build_timeline(
            TimelineLayers(narration=narration_from_documents(narrative, timing))
        )
        assert _load(tmp_path / "upstream" / "timeline.json") == expected.model_dump(mode="json")
        exemplar = tmp_path / "upstream" / "exemplar" / "canvas-techniques.js"
        assert "EXEMPLAR" in exemplar.read_text(encoding="utf-8")
        assert not (tmp_path / "upstream" / "timeline.error.txt").exists()

    def test_missing_upstream_does_not_raise_and_records_a_reason(self, tmp_path: Path) -> None:
        STAGE.prepare_turn(tmp_path)
        assert not (tmp_path / "upstream" / "timeline.json").exists()
        reason = (tmp_path / "upstream" / "timeline.error.txt").read_text(encoding="utf-8")
        assert "narrative" in reason

    def test_inconsistent_timing_does_not_raise(self, tmp_path: Path) -> None:
        _upstream(tmp_path)
        timing_path = tmp_path / "upstream" / "narrative" / "timing.json"
        timing = _load(timing_path)
        timing["scenes"][0]["beats"].pop()
        timing_path.write_text(json.dumps(timing), encoding="utf-8")
        STAGE.prepare_turn(tmp_path)
        reason = (tmp_path / "upstream" / "timeline.error.txt").read_text(encoding="utf-8")
        assert "s-hook" in reason and "beat 数" in reason

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda t: t["scenes"][0]["beats"][0].pop("start_seconds"),
            lambda t: t["scenes"][0].update(beats=None),
        ],
        ids=["missing-field", "null-beats"],
    )
    def test_structurally_malformed_timing_does_not_raise(self, tmp_path: Path, mutate) -> None:
        _upstream(tmp_path)
        timing_path = tmp_path / "upstream" / "narrative" / "timing.json"
        timing = _load(timing_path)
        mutate(timing)
        timing_path.write_text(json.dumps(timing), encoding="utf-8")
        STAGE.prepare_turn(tmp_path)
        assert not (tmp_path / "upstream" / "timeline.json").exists()
        assert (tmp_path / "upstream" / "timeline.error.txt").is_file()

    def test_error_text_does_not_repeat_the_unavailable_prefix(self, tmp_path: Path) -> None:
        _upstream(tmp_path)
        timing_path = tmp_path / "upstream" / "narrative" / "timing.json"
        timing = _load(timing_path)
        timing["scenes"][0]["beats"].pop()
        timing_path.write_text(json.dumps(timing), encoding="utf-8")
        STAGE.prepare_turn(tmp_path)
        reason = (tmp_path / "upstream" / "timeline.error.txt").read_text(encoding="utf-8")
        assert "时间轴不可用" not in reason

    def test_corrupt_json_does_not_raise(self, tmp_path: Path) -> None:
        _upstream(tmp_path)
        (tmp_path / "upstream" / "narrative" / "narrative.json").write_text("{", encoding="utf-8")
        STAGE.prepare_turn(tmp_path)
        assert (tmp_path / "upstream" / "timeline.error.txt").is_file()

    def test_a_failure_removes_the_stale_timeline_and_recovery_removes_the_error(
        self, tmp_path: Path
    ) -> None:
        _upstream(tmp_path)
        STAGE.prepare_turn(tmp_path)
        assert (tmp_path / "upstream" / "timeline.json").is_file()

        timing_path = tmp_path / "upstream" / "narrative" / "timing.json"
        good = timing_path.read_text(encoding="utf-8")
        timing_path.write_text(json.dumps({"scenes": []}), encoding="utf-8")
        STAGE.prepare_turn(tmp_path)
        assert not (tmp_path / "upstream" / "timeline.json").exists()
        assert (tmp_path / "upstream" / "timeline.error.txt").is_file()

        timing_path.write_text(good, encoding="utf-8")
        STAGE.prepare_turn(tmp_path)
        assert (tmp_path / "upstream" / "timeline.json").is_file()
        assert not (tmp_path / "upstream" / "timeline.error.txt").exists()


class TestPrepareTurnForMusicProjects:
    """短片与"讲解 + 背景乐"：时间轴带网格与配乐层（子项目 3 设计 §6.3）。"""

    @staticmethod
    def _beatsheet(workdir: Path) -> None:
        path = workdir / "upstream" / "beatsheet" / "beatsheet.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "bpm": 128,
                    "sections": [
                        {
                            "id": "s1",
                            "label": "A",
                            "bars": 3,
                            "intent": "x",
                            "energy": "low",
                            "moments": [{"at": "1.1", "visual_action": "开场"}],
                        },
                        {"id": "s2", "label": "B", "bars": 3, "intent": "x", "energy": "peak"},
                    ],
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _music(
        workdir: Path, *, bpm: float = 128, duration: float = 11.25, **extra: object
    ) -> None:
        folder = workdir / "upstream" / "music"
        folder.mkdir(parents=True, exist_ok=True)
        events = [{"name": "kick", "kind": "onset", "start": 0.0, "end": 0.2}]
        (folder / "events.json").write_text(
            json.dumps({"bpm": bpm, "duration": duration, "events": events, **extra}),
            encoding="utf-8",
        )
        (folder / "analysis.json").write_text(
            json.dumps({"hop": 0.1, "energy": [0.1, 0.5]}), encoding="utf-8"
        )

    def test_a_reel_gets_grid_moments_and_music_without_narration(self, tmp_path: Path) -> None:
        self._beatsheet(tmp_path)
        self._music(tmp_path)
        STAGE.prepare_turn(tmp_path)
        timeline = _load(tmp_path / "upstream" / "timeline.json")
        assert timeline["narration"] == []
        assert timeline["grid"]["bpm"] == 128
        assert [s["id"] for s in timeline["sections"]] == ["s1", "s2"]
        assert timeline["moments"][0]["at"] == "1.1"
        assert timeline["music"]["events"][0]["name"] == "kick"
        assert not (tmp_path / "upstream" / "timeline.error.txt").exists()

    def test_a_reel_without_the_rendered_music_names_the_missing_files(
        self, tmp_path: Path
    ) -> None:
        self._beatsheet(tmp_path)
        STAGE.prepare_turn(tmp_path)
        reason = (tmp_path / "upstream" / "timeline.error.txt").read_text(encoding="utf-8")
        assert "music/events.json" in reason
        assert not (tmp_path / "upstream" / "timeline.json").exists()

    def test_a_reel_whose_music_disagrees_with_the_beatsheet_is_reported(
        self, tmp_path: Path
    ) -> None:
        self._beatsheet(tmp_path)
        self._music(tmp_path, bpm=100)
        STAGE.prepare_turn(tmp_path)
        reason = (tmp_path / "upstream" / "timeline.error.txt").read_text(encoding="utf-8")
        assert "bpm" in reason

    def test_an_explainer_with_a_background_bed_takes_the_grid_from_the_declared_bpm(
        self, tmp_path: Path
    ) -> None:
        _upstream(tmp_path)
        self._music(tmp_path, bpm=100, duration=3.0, offset=0.1)
        STAGE.prepare_turn(tmp_path)
        timeline = _load(tmp_path / "upstream" / "timeline.json")
        assert timeline["grid"]["bpm"] == 100 and timeline["grid"]["offset"] == pytest.approx(0.1)
        assert len(timeline["narration"]) == 2 and timeline["music"] is not None

    def test_an_explainer_without_music_is_unchanged(self, tmp_path: Path) -> None:
        _upstream(tmp_path)
        STAGE.prepare_turn(tmp_path)
        timeline = _load(tmp_path / "upstream" / "timeline.json")
        assert timeline["grid"] is None and timeline["music"] is None

    def test_the_beatsheet_stays_readable_for_the_agent(self, tmp_path: Path) -> None:
        self._beatsheet(tmp_path)
        self._music(tmp_path)
        STAGE.prepare_turn(tmp_path)
        assert (tmp_path / "upstream" / "beatsheet" / "beatsheet.json").is_file()


class TestPrepareTurnForMusicMv:
    """导入音乐 MV：`upstream/music/sections.json` 存在即走导入来源（4A T8）。"""

    ANALYSIS = {
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
    SECTIONS = {
        "sections": [
            {"id": "intro", "label": "Intro", "start": 0.5, "end": 4.5},
            {"id": "verse", "label": "Verse", "start": 4.5, "end": 8.5},
        ]
    }
    BEATSHEET = {
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

    @staticmethod
    def _write(workdir: Path, relpath: str, data: object) -> None:
        path = workdir / "upstream" / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _mv(self, workdir: Path) -> None:
        music = workdir / "upstream" / "music"
        music.mkdir(parents=True, exist_ok=True)
        (music / "source.mp3").write_bytes(b"ID3fake")
        self._write(workdir, "music/analysis.json", self.ANALYSIS)
        self._write(workdir, "music/sections.json", self.SECTIONS)
        self._write(workdir, "beatsheet/beatsheet.json", self.BEATSHEET)

    def test_an_mv_gets_the_import_timeline(self, tmp_path: Path) -> None:
        self._mv(tmp_path)
        STAGE.prepare_turn(tmp_path)
        timeline = _load(tmp_path / "upstream" / "timeline.json")
        assert timeline["narration"] == []
        assert [(s["id"], s["start"], s["end"]) for s in timeline["sections"]] == [
            ("intro", 0.0, 4.0),
            ("verse", 4.0, 8.0),
        ]
        assert timeline["grid"]["bpm"] == 120.0
        assert timeline["music"]["file"] == "music/source.mp3"
        assert timeline["music"]["events"] == []
        assert timeline["music"]["energy"]["hop"] == 0.5
        assert timeline["moments"][0]["section_id"] == "verse"
        assert not (tmp_path / "upstream" / "timeline.error.txt").exists()

    def test_missing_sections_json_falls_back_to_the_synth_path(self, tmp_path: Path) -> None:
        self._mv(tmp_path)
        (tmp_path / "upstream" / "music" / "sections.json").unlink()
        STAGE.prepare_turn(tmp_path)
        reason = (tmp_path / "upstream" / "timeline.error.txt").read_text(encoding="utf-8")
        assert "bpm 必须是数字" in reason  # the synth loader rejects an MV beatsheet
        assert not (tmp_path / "upstream" / "timeline.json").exists()

    def test_a_ref_that_matches_no_section_is_reported_and_clears_the_stale_timeline(
        self, tmp_path: Path
    ) -> None:
        self._mv(tmp_path)
        STAGE.prepare_turn(tmp_path)
        assert (tmp_path / "upstream" / "timeline.json").is_file()
        bad = json.loads(json.dumps(self.BEATSHEET))
        bad["sections"][1]["ref"] = "bridge"
        self._write(tmp_path, "beatsheet/beatsheet.json", bad)
        STAGE.prepare_turn(tmp_path)
        reason = (tmp_path / "upstream" / "timeline.error.txt").read_text(encoding="utf-8")
        assert "bridge" in reason
        assert not (tmp_path / "upstream" / "timeline.json").exists()

    def test_a_missing_source_audio_is_reported(self, tmp_path: Path) -> None:
        self._mv(tmp_path)
        (tmp_path / "upstream" / "music" / "source.mp3").unlink()
        STAGE.prepare_turn(tmp_path)
        reason = (tmp_path / "upstream" / "timeline.error.txt").read_text(encoding="utf-8")
        assert "music/source" in reason
