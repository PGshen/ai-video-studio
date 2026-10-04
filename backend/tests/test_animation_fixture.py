"""`fixtures/animation/seed.py` 的 `seed_animation_project` 行为（M2 T4）。

覆盖计划里写的两条断言：种子脚本跑完后 animation 阶段从 `locked` 变
`active`；`upstream/narrative/` 下能读到 fixture 内容（走
`workspace.upstream` 的物化逻辑，模拟 TurnRunner 在一轮开始前做的事）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from conftest import AnimationProjectEnv
from fixtures.animation.seed import fixture_registry, seed_animation_project
from studio.agent.stage_flow import upstream_sources
from studio.db.engine import make_engine, migrate
from studio.db.repo.stages import get_stage
from studio.stages.animation import STAGE as ANIMATION_STAGE
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


class TestSeedAnimationProject:
    def test_returns_project_id_and_unlocks_animation_stage(
        self, engine: Engine, blobs: BlobStore, data_dir: Path
    ) -> None:
        project_id = seed_animation_project(engine, blobs, data_dir=data_dir)

        assert isinstance(project_id, str) and project_id

        narrative = get_stage(engine, project_id, "narrative")
        assert narrative is not None and narrative.status == "finalized"

        animation = get_stage(engine, project_id, "animation")
        assert animation is not None and animation.status == "active"

    def test_upstream_narrative_is_readable_after_materialize(
        self, engine: Engine, blobs: BlobStore, data_dir: Path
    ) -> None:
        project_id = seed_animation_project(engine, blobs, data_dir=data_dir)
        workdir = project_dir(data_dir, project_id)

        sources = upstream_sources(engine, fixture_registry(), project_id, ANIMATION_STAGE.name)
        materialize_upstream(workdir, blobs, sources)

        upstream_narrative = workdir / "upstream" / "narrative"
        narrative_json = (upstream_narrative / "narrative.json").read_text(encoding="utf-8")
        assert '"s-hook"' in narrative_json
        assert '"s-explain"' in narrative_json

        timing_json = (upstream_narrative / "timing.json").read_text(encoding="utf-8")
        assert '"duration_seconds"' in timing_json

        for filename in ("s-hook.wav", "s-explain.wav"):
            audio_bytes = (upstream_narrative / "audio" / filename).read_bytes()
            assert len(audio_bytes) > 0

    def test_each_call_creates_an_independent_project(
        self, engine: Engine, blobs: BlobStore, data_dir: Path
    ) -> None:
        first = seed_animation_project(engine, blobs, data_dir=data_dir)
        second = seed_animation_project(engine, blobs, data_dir=data_dir)

        assert first != second
        assert get_stage(engine, second, "animation") is not None


class TestAnimationProjectFixture:
    """`conftest.py` 里包装成 pytest fixture 的同一个种子函数，供 T5/T7/T8/T14 使用。"""

    def test_fixture_wires_up_a_usable_project(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        stage = get_stage(animation_project.engine, animation_project.project_id, "animation")
        assert stage is not None and stage.status == "active"
        assert (animation_project.workdir / "narrative" / "narrative.json").exists()
