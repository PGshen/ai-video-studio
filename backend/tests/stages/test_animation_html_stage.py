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
