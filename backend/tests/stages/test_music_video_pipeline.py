"""Music-video pipeline end to end (4A T9): real stages, real song analysis, real stage_flow.

concept -> music (analyze_music + sections.json) -> beatsheet (ref form) -> animation_html
(prepare_turn reads the MV timeline); re-analysing the music marks the downstream stale.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures.import_music import write_click_song
from studio.agent.stage import StageRegistry, upstream_of
from studio.agent.stage_flow import finalize, initial_statuses, reopen
from studio.agent.tools import ToolContext, invoke_tool
from studio.db.engine import make_engine, migrate
from studio.db.repo.projects import create_project
from studio.db.repo.stages import create_stage, get_stage
from studio.engines.render.html.probe import is_reel
from studio.stages.animation_html import STAGE as ANIMATION_HTML
from studio.stages.beatsheet import STAGE as BEATSHEET
from studio.stages.beatsheet.validate_beatsheet import check_workspace as check_beatsheet
from studio.stages.concept import STAGE as CONCEPT
from studio.stages.music import STAGE as MUSIC
from studio.stages.music.analyze import ANALYZE_MUSIC_TOOL
from studio.stages.music.validate_sections import check_workspace as check_sections
from studio.stages.pipeline import ProjectKind, build_pipeline
from studio.workspace import BlobStore, create_snapshot, project_dir

PIPELINE = ["concept", "music", "beatsheet", "animation_html"]

# 120 BPM click track with the first downbeat at 0.5 s: downbeats every 2 s.
SECTIONS = {
    "sections": [
        {"id": "intro", "label": "Intro", "start": 0.5, "end": 8.5},
        {"id": "verse", "label": "Verse", "start": 8.5, "end": 16.5},
    ]
}
BEATSHEET_DOC = {
    "sections": [
        {"ref": "intro", "intent": "起", "energy": "low", "moments": []},
        {
            "ref": "verse",
            "intent": "承",
            "energy": "high",
            "moments": [{"at": "1.3", "visual_action": "闪"}],
        },
    ]
}


def _registry() -> StageRegistry:
    registry = StageRegistry()
    for stage in (CONCEPT, MUSIC, BEATSHEET, ANIMATION_HTML):
        registry.register(stage)
    return registry


def _analyze(workdir: Path) -> None:
    ctx = ToolContext(
        project_id="p", stage="music", workdir=workdir, record_tool_write=lambda rel, digest: None
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

    def import_music(self) -> None:
        music = self.workdir / "music"
        music.mkdir(parents=True, exist_ok=True)
        for name in ("source.wav", "analysis.json", "analysis.png"):
            shutil.copyfile(self.analysed / "music" / name, music / name)
        _write_json(music / "sections.json", SECTIONS)

    def upstream_for_downstream(self) -> Path:
        """The directory a downstream turn would see: music/ and beatsheet/ under upstream/."""
        target = self.workdir / "upstream"
        shutil.rmtree(target, ignore_errors=True)
        for name in ("music", "beatsheet"):
            if (self.workdir / name).is_dir():
                shutil.copytree(self.workdir / name, target / name)
        return self.workdir


@pytest.fixture
def project(tmp_path: Path, analysed: Path) -> Iterator[_Project]:
    value = _Project(tmp_path, analysed)
    yield value
    value.engine.dispose()


def test_pipeline_order_and_upstreams() -> None:
    assert build_pipeline(ProjectKind("html", False, "import")) == PIPELINE
    registry = _registry()
    assert upstream_of(PIPELINE, registry, "concept") == []
    assert upstream_of(PIPELINE, registry, "music") == ["concept"]
    assert upstream_of(PIPELINE, registry, "beatsheet") == ["concept", "music"]
    assert upstream_of(PIPELINE, registry, "animation_html") == ["music", "beatsheet"]


def test_the_four_stages_chain_into_an_mv_timeline(project: _Project) -> None:
    project.write_concept()
    project.finalize("concept")
    assert project.stage("music").status == "active"

    # music: real analysis products + a hand-written sections.json
    project.import_music()
    assert check_sections(project.workdir).ok
    assert MUSIC.finalize_blockers(project.workdir) == []
    project.finalize("music")
    assert project.stage("beatsheet").status == "active"

    # beatsheet: ref form validated against the upstream sections
    work = project.upstream_for_downstream()
    _write_json(work / "beatsheet" / "beatsheet.json", BEATSHEET_DOC)
    checked = check_beatsheet(work)
    assert checked.errors == []
    assert BEATSHEET.finalize_blockers(work) == []
    project.finalize("beatsheet")
    assert project.stage("animation_html").status == "active"

    # animation_html: prepare_turn reads the MV timeline
    work = project.upstream_for_downstream()
    ANIMATION_HTML.prepare_turn(work)
    assert not (work / "upstream" / "timeline.error.txt").exists()
    timeline = json.loads((work / "upstream" / "timeline.json").read_text(encoding="utf-8"))
    assert is_reel(timeline)
    assert timeline["narration"] == []
    assert [(s["id"], s["start"], s["end"]) for s in timeline["sections"]] == [
        ("intro", 0.0, 8.0),
        ("verse", 8.0, 16.0),
    ]
    assert timeline["grid"]["bpm"] == pytest.approx(120.0, rel=0.01)
    assert timeline["music"]["file"] == "music/source.wav"
    assert timeline["moments"][0]["section_id"] == "verse"
    project.finalize("animation_html")
    assert project.stage("animation_html").status == "finalized"


def _finalize_all(project: _Project) -> None:
    project.write_concept()
    project.finalize("concept")
    project.import_music()
    project.finalize("music")
    work = project.upstream_for_downstream()
    _write_json(work / "beatsheet" / "beatsheet.json", BEATSHEET_DOC)
    project.finalize("beatsheet")
    project.finalize("animation_html")
    for name in PIPELINE:
        assert project.stage(name).status == "finalized"


def test_changed_sections_mark_beatsheet_and_animation_stale(project: _Project) -> None:
    _finalize_all(project)
    project.reopen("music")
    shorter = {"sections": SECTIONS["sections"][:1]}
    _write_json(project.workdir / "music" / "sections.json", shorter)
    project.finalize("music")
    assert project.stage("beatsheet").status == "stale"
    assert project.stage("animation_html").status == "stale"
    assert project.stage("concept").status == "finalized"


def test_reanalysing_a_replaced_song_marks_the_downstream_stale(project: _Project) -> None:
    _finalize_all(project)
    project.reopen("music")
    write_click_song(project.workdir / "music" / "source.wav", bpm=100.0, offset=0.8)
    assert any("重新 analyze_music" in b for b in MUSIC.finalize_blockers(project.workdir))
    _analyze(project.workdir)
    analysis = json.loads((project.workdir / "music" / "analysis.json").read_text("utf-8"))
    assert analysis["bpm"] == pytest.approx(100.0, rel=0.01)
    # the old sections no longer sit on downbeats of the new grid
    errors = check_sections(project.workdir).errors
    # every boundary is reported as off-grid (the fitted downbeat floats are not pinned)
    assert [error.split(" s 没有落在强拍上（最近的强拍 ")[0] for error in errors] == [
        "段落 intro 的起点 0.5",
        "段落 intro 的终点 8.5",
        "段落 verse 的起点 8.5",
        "段落 verse 的终点 16.5",
    ]
    _write_json(
        project.workdir / "music" / "sections.json",
        {
            "sections": [
                {"id": "intro", "label": "Intro", "start": 0.8, "end": 10.4},
                {"id": "verse", "label": "Verse", "start": 10.4, "end": 17.6},
            ]
        },
    )
    assert MUSIC.finalize_blockers(project.workdir) == []
    project.finalize("music")
    assert project.stage("beatsheet").status == "stale"
    assert project.stage("animation_html").status == "stale"


def test_an_unchanged_music_stage_keeps_the_downstream_finalized(project: _Project) -> None:
    _finalize_all(project)
    project.reopen("music")
    project.finalize("music")
    assert project.stage("beatsheet").status == "finalized"
    assert project.stage("animation_html").status == "finalized"
