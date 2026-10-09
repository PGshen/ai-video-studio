from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import Engine

from studio.agent.stage import StageRegistry
from studio.db.engine import make_engine, migrate
from studio.db.repo.projects import create_project
from studio.db.repo.stages import create_stage
from studio.stages.animation_html import STAGE as ANIMATION
from studio.stages.narrative import STAGE as NARRATIVE
from studio.stages.topic import STAGE as TOPIC
from studio.workspace import BlobStore, create_snapshot, project_dir

EXPLAINER_SETTINGS = {
    "video_kind": "explainer_html",
    "engine": "html",
    "narration": True,
    "music_source": "none",
    "pipeline": ["topic", "narrative", "animation_html"],
}


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    d = project_dir(tmp_path / "data", "proj-1")
    d.mkdir(parents=True)
    return d


@dataclass
class StudioEnv:
    """A migrated DB, a blob store, the three explainer stages and one HTML explainer project
    whose stage rows start as topic=active, narrative/animation_html=locked (the state project
    creation produces)."""

    data_dir: Path
    engine: Engine
    blobs: BlobStore
    registry: StageRegistry
    project_id: str

    @property
    def workdir(self) -> Path:
        return project_dir(self.data_dir, self.project_id)

    def write(self, relpath: str, content: str) -> None:
        """Simulate a user edit (or any out-of-band change) to the workspace."""
        path = self.workdir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def new_project(self, title: str = "另一个项目") -> str:
        project = create_project(self.engine, title=title, settings=dict(EXPLAINER_SETTINGS))
        _init_project(self, project.id)
        return project.id


def _init_project(env: StudioEnv, project_id: str) -> None:
    for stage, status in (
        ("topic", "active"),
        ("narrative", "locked"),
        ("animation_html", "locked"),
    ):
        create_stage(env.engine, project_id=project_id, stage=stage, status=status)
    style = project_dir(env.data_dir, project_id) / "style" / "STYLE.md"
    style.parent.mkdir(parents=True, exist_ok=True)
    style.write_text("# 风格\n", encoding="utf-8")
    create_snapshot(env.engine, env.blobs, project_id, reason="init")


@pytest.fixture
def env(tmp_path: Path) -> Iterator[StudioEnv]:
    data_dir = tmp_path / "data"
    engine = make_engine(tmp_path / "studio.db")
    migrate(engine)
    registry = StageRegistry()
    for stage in (TOPIC, NARRATIVE, ANIMATION):
        registry.register(stage)
    project = create_project(engine, title="测试项目", settings=dict(EXPLAINER_SETTINGS))
    studio_env = StudioEnv(
        data_dir=data_dir,
        engine=engine,
        blobs=BlobStore(data_dir / "blobs"),
        registry=registry,
        project_id=project.id,
    )
    _init_project(studio_env, project.id)
    yield studio_env
    engine.dispose()
