"""`concept → produce` end to end: real stages, real song analysis, real `stage_flow`.

Both silent forms (reel, music video) use the same two stages. The song is uploaded and analysed
in `concept`; changing it there and re-finalizing marks `produce` stale.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures.html_engine import projects as fx
from fixtures.import_music import write_click_song
from fixtures.synth_music.products import render_free_products
from studio.agent.stage import StageRegistry, upstream_of
from studio.agent.stage_flow import finalize, initial_statuses, reopen
from studio.agent.tools import ToolContext, invoke_tool
from studio.db.engine import make_engine, migrate
from studio.db.repo.projects import create_project
from studio.db.repo.stages import create_stage, get_stage
from studio.engines.render.html.probe import is_reel
from studio.stages.common.score.analyze import ANALYZE_MUSIC_TOOL
from studio.stages.concept import STAGE as CONCEPT
from studio.stages.pipeline import ProjectKind, build_pipeline
from studio.stages.produce import STAGE as PRODUCE
from studio.timeline.load import TimelineSources, load_timeline
from studio.workspace import BlobStore, create_snapshot, project_dir

PIPELINE = ["concept", "produce"]
SONG_SECONDS = 20.0


def _registry() -> StageRegistry:
    registry = StageRegistry()
    for stage in (CONCEPT, PRODUCE):
        registry.register(stage)
    return registry


def _analyze(workdir: Path, stage: str = "concept") -> None:
    ctx = ToolContext(
        project_id="p", stage=stage, workdir=workdir, record_tool_write=lambda rel, digest: None
    )
    result = asyncio.run(invoke_tool(ANALYZE_MUSIC_TOOL, ctx, {}))
    assert not result.is_error, result.text


@pytest.fixture(scope="module")
def analysed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One real analysis (numba cold start ~27 s) of a 120 BPM click song, shared read-only."""
    root = tmp_path_factory.mktemp("mv-analysed")
    (root / "music").mkdir()
    write_click_song(root / "music" / "source.wav")
    _analyze(root)
    return root


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class _Project:
    def __init__(self, tmp_path: Path, analysed: Path) -> None:
        self.data_dir = tmp_path / "data"
        self.engine = make_engine(tmp_path / "studio.db")
        migrate(self.engine)
        self.blobs = BlobStore(self.data_dir / "blobs")
        self.registry = _registry()
        project = create_project(self.engine, title="MV", settings={"pipeline": PIPELINE})
        self.project_id = project.id
        for name, status in initial_statuses(PIPELINE, self.registry):
            create_stage(self.engine, project_id=project.id, stage=name, status=status)
        self.workdir = project_dir(self.data_dir, project.id)
        self.workdir.mkdir(parents=True)
        create_snapshot(self.engine, self.blobs, project.id, reason="init")
        self.analysed = analysed

    def stage(self, name: str):
        value = get_stage(self.engine, self.project_id, name)
        assert value is not None
        return value

    def finalize(self, name: str) -> None:
        finalize(self.engine, self.blobs, self.registry, self.project_id, name)

    def reopen(self, name: str) -> None:
        reopen(self.engine, self.project_id, name)

    def write_concept(self, text: str = "# 简报\n") -> None:
        path = self.workdir / "concept" / "brief.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def upload_and_analyse(self) -> None:
        """What the concept stage does for a song project: upload, then `analyze_music`."""
        music = self.workdir / "music"
        music.mkdir(parents=True, exist_ok=True)
        for name in ("source.wav", "analysis.json", "analysis.png"):
            shutil.copyfile(self.analysed / "music" / name, music / name)

    def write_shots_and_scenes(self, length: float = SONG_SECONDS) -> None:
        half = length / 2
        _write_json(
            self.workdir / "animation" / "shots.json",
            {
                "shots": [
                    {"id": "intro", "label": "Intro", "start": 0.0, "end": half},
                    {"id": "verse", "label": "Verse", "start": half, "end": length},
                ]
            },
        )
        fx.write_project(
            self.workdir, scenes={"intro": fx.PURE_SCENE_PLAIN, "verse": fx.PURE_SCENE_PLAIN}
        )


@pytest.fixture
def project(tmp_path: Path, analysed: Path) -> Iterator[_Project]:
    value = _Project(tmp_path, analysed)
    yield value
    value.engine.dispose()


def test_both_silent_forms_use_the_same_two_stages() -> None:
    assert build_pipeline(ProjectKind("html", False, "import")) == PIPELINE
    assert build_pipeline(ProjectKind("html", False, "synth")) == PIPELINE
    registry = _registry()
    assert upstream_of(PIPELINE, registry, "concept") == []
    assert upstream_of(PIPELINE, registry, "produce") == ["concept"]


def test_the_two_stages_chain_into_an_mv_timeline(project: _Project) -> None:
    project.write_concept()
    project.upload_and_analyse()
    project.finalize("concept")
    assert project.stage("produce").status == "active"

    # produce: shots + scenes (no sections.json, no beat sheet), optional range
    project.write_shots_and_scenes()
    assert PRODUCE.finalize_blockers(project.workdir) == []
    loaded = load_timeline(TimelineSources(project.workdir, False, "import", produce=True))
    timeline = loaded.timeline.model_dump(mode="json")
    assert is_reel(timeline) and timeline["narration"] == []
    assert [(s["id"], s["start"], s["end"]) for s in timeline["sections"]] == [
        ("intro", 0.0, 10.0),
        ("verse", 10.0, 20.0),
    ]
    assert timeline["grid"] is None and timeline["moments"] == []
    assert timeline["music"]["file"] == "music/source.wav"
    assert {"beat", "downbeat"} <= {e["name"] for e in timeline["music"]["events"]}
    project.finalize("produce")
    assert project.stage("produce").status == "finalized"


def test_a_range_narrows_the_timeline_to_that_part_of_the_song(project: _Project) -> None:
    project.write_concept()
    project.upload_and_analyse()
    project.finalize("concept")
    _write_json(project.workdir / "music" / "range.json", {"start": 4.0, "end": 14.0})
    project.write_shots_and_scenes(length=10.0)
    assert PRODUCE.finalize_blockers(project.workdir) == []
    loaded = load_timeline(TimelineSources(project.workdir, False, "import", produce=True))
    assert loaded.range == (4.0, 14.0) and loaded.timeline.duration == pytest.approx(10.0)


async def test_a_reel_chains_the_same_way(tmp_path: Path, analysed: Path) -> None:
    project = _Project(tmp_path, analysed)
    try:
        project.write_concept()
        project.finalize("concept")
        outcome = await render_free_products(project.workdir)
        assert outcome.ok
        project.write_shots_and_scenes(length=16.0)
        assert PRODUCE.finalize_blockers(project.workdir) == []
        project.finalize("produce")
        assert project.stage("produce").status == "finalized"
    finally:
        project.engine.dispose()


def _finalize_all(project: _Project) -> None:
    project.write_concept()
    project.upload_and_analyse()
    project.finalize("concept")
    project.write_shots_and_scenes()
    project.finalize("produce")
    for name in PIPELINE:
        assert project.stage(name).status == "finalized"


def test_changing_the_song_in_concept_marks_produce_stale(project: _Project) -> None:
    _finalize_all(project)
    project.reopen("concept")
    write_click_song(project.workdir / "music" / "source.wav", bpm=100.0, offset=0.8)
    _analyze(project.workdir)
    analysis = json.loads((project.workdir / "music" / "analysis.json").read_text("utf-8"))
    assert analysis["bpm"] == pytest.approx(100.0, rel=0.01)
    project.finalize("concept")
    assert project.stage("produce").status == "stale"


def test_a_new_brief_marks_produce_stale(project: _Project) -> None:
    _finalize_all(project)
    project.reopen("concept")
    project.write_concept("# 新的简报\n")
    project.finalize("concept")
    assert project.stage("produce").status == "stale"


def test_an_unchanged_concept_keeps_produce_finalized(project: _Project) -> None:
    _finalize_all(project)
    project.reopen("concept")
    project.finalize("concept")
    assert project.stage("produce").status == "finalized"
