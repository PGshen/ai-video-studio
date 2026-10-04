"""`fixtures/narrative/seed.py` 的 `seed_narrative_project` 行为（M3 T4）。

对称于 `test_animation_fixture.py`（M2 T4）：种子脚本跑完后叙事阶段从
`locked` 变 `active`；`upstream/topic/` 下能读到 fixture 内容。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from conftest import NarrativeProjectEnv
from fixtures.narrative.seed import fixture_registry, seed_narrative_project
from studio.agent.stage_flow import upstream_sources
from studio.db.engine import make_engine, migrate
from studio.db.repo.stages import get_stage
from studio.stages.narrative import STAGE as NARRATIVE_STAGE
from studio.workspace import BlobStore, materialize_upstream, project_dir


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "studio.db")
    migrate(eng)
    return eng


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "data" / "blobs")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


class TestSeedNarrativeProject:
    def test_returns_project_id_and_unlocks_narrative_stage(
        self, engine: Engine, blobs: BlobStore, data_dir: Path
    ) -> None:
        project_id = seed_narrative_project(engine, blobs, data_dir=data_dir)

        assert isinstance(project_id, str) and project_id

        topic = get_stage(engine, project_id, "topic")
        assert topic is not None and topic.status == "finalized"

        narrative = get_stage(engine, project_id, "narrative")
        assert narrative is not None and narrative.status == "active"

    def test_upstream_topic_is_readable_after_materialize(
        self, engine: Engine, blobs: BlobStore, data_dir: Path
    ) -> None:
        project_id = seed_narrative_project(engine, blobs, data_dir=data_dir)
        workdir = project_dir(data_dir, project_id)

        sources = upstream_sources(engine, fixture_registry(), project_id, NARRATIVE_STAGE.name)
        materialize_upstream(workdir, blobs, sources)

        brief = (workdir / "upstream" / "topic" / "brief.md").read_text(encoding="utf-8")
        assert "核心问题" in brief

    def test_each_call_creates_an_independent_project(
        self, engine: Engine, blobs: BlobStore, data_dir: Path
    ) -> None:
        first = seed_narrative_project(engine, blobs, data_dir=data_dir)
        second = seed_narrative_project(engine, blobs, data_dir=data_dir)

        assert first != second
        assert get_stage(engine, second, "narrative") is not None


class TestNarrativeProjectFixture:
    """`conftest.py` 里包装成 pytest fixture 的同一个种子函数，供 T5/T6/T8 使用。"""

    def test_fixture_wires_up_a_usable_project(
        self, narrative_project: NarrativeProjectEnv
    ) -> None:
        stage = get_stage(narrative_project.engine, narrative_project.project_id, "narrative")
        assert stage is not None and stage.status == "active"
        assert (narrative_project.workdir / "topic" / "brief.md").exists()
