"""“叙事已定稿、`animation_html` 阶段已解锁”的 `explainer_html` 项目种子（2A T8）。

和 `fixtures.animation.seed.seed_animation_project` 同一套做法，区别是项目 `settings` 带类型字段
和 `pipeline`，阶段是 `topic → narrative → animation_html`。叙事产物复用 `fixtures/animation/`。
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine

from fixtures.animation.seed import _write_narrative_artifacts
from studio.agent.stage import StageRegistry
from studio.agent.stage_flow import finalize
from studio.db.repo.projects import create_project
from studio.db.repo.stages import create_stage
from studio.stages.animation_html import STAGE as ANIMATION_HTML_STAGE
from studio.stages.narrative import STAGE as NARRATIVE_STAGE
from studio.stages.topic import STAGE as TOPIC_STAGE
from studio.workspace import BlobStore, create_snapshot, init_workspace

PIPELINE = ["topic", "narrative", "animation_html"]


def html_registry() -> StageRegistry:
    registry = StageRegistry()
    for stage in (TOPIC_STAGE, NARRATIVE_STAGE, ANIMATION_HTML_STAGE):
        registry.register(stage)
    return registry


def seed_animation_html_project(engine: Engine, blobs: BlobStore, *, data_dir: Path) -> str:
    registry = html_registry()
    project = create_project(
        engine,
        id=uuid4().hex,
        title="HTML 动画 fixture 项目",
        settings={
            "video_kind": "explainer_html",
            "engine": "html",
            "narration": True,
            "music_source": "none",
            "pipeline": PIPELINE,
        },
    )
    for index, stage in enumerate(PIPELINE):
        create_stage(
            engine,
            project_id=project.id,
            stage=stage,
            status="active" if index == 0 else "locked",
        )
    workdir = init_workspace(
        data_dir, project.id, {"style/STYLE.md": "# 风格\n\n（fixture 占位）\n"}
    )
    create_snapshot(engine, blobs, project.id, reason="init")
    finalize(engine, blobs, registry, project.id, "topic")
    _write_narrative_artifacts(workdir)
    finalize(engine, blobs, registry, project.id, "narrative")
    return project.id
