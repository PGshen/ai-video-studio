"""手工准备的"选题已定稿"种子脚本（M3 T4，对称于 M2 T4 的
`fixtures/animation/seed.py`）。

M4 的选题打磨 agent 还没实现，本计划（M3 叙事阶段）的其余任务需要一个从
"选题已定稿"状态开始的项目才能测试。`seed_narrative_project` 绕过真正的
topic agent：直接创建项目、把本目录下手工准备的 `brief.md` 写进工作区的
`topic/` 产物目录，再走 `stage_flow.finalize` 定稿 topic，让 `narrative`
阶段从 `locked` 变成 `active`。
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine

from studio.agent.stage import StageRegistry
from studio.agent.stage_flow import finalize
from studio.db.repo.projects import create_project
from studio.db.repo.stages import create_stage
from studio.stages.animation import STAGE as ANIMATION_STAGE
from studio.stages.narrative import STAGE as NARRATIVE_STAGE
from studio.stages.topic import STAGE as TOPIC_STAGE
from studio.workspace import BlobStore, create_snapshot, init_workspace

_FIXTURE_DIR = Path(__file__).parent

_INITIAL_STAGES: tuple[tuple[str, str], ...] = (
    ("topic", "active"),
    ("narrative", "locked"),
    ("animation", "locked"),
)


def fixture_registry() -> StageRegistry:
    """只含三个占位阶段的 registry，只供本函数驱动 `stage_flow.finalize`
    使用（和 `main.create_app` 组装出的 registry 里的 `STAGE` 是同一批单例）。
    """
    registry = StageRegistry()
    for stage in (TOPIC_STAGE, NARRATIVE_STAGE, ANIMATION_STAGE):
        registry.register(stage)
    return registry


def seed_narrative_project(engine: Engine, blobs: BlobStore, *, data_dir: Path) -> str:
    """建一个"选题已定稿、叙事阶段已解锁"的项目，返回 `project_id`。

    流程：建项目 → 把本目录下的 `brief.md` 写进工作区 `topic/brief.md` →
    定稿 topic（narrative 因此从 `locked` 变 `active`）。
    """
    registry = fixture_registry()
    project = create_project(engine, id=uuid4().hex, title="叙事阶段 fixture 项目")
    project_id = project.id

    for stage, status in _INITIAL_STAGES:
        create_stage(engine, project_id=project_id, stage=stage, status=status)

    style = {"style/STYLE.md": "# 风格\n\n（fixture 占位）\n"}
    workdir = init_workspace(data_dir, project_id, style)
    create_snapshot(engine, blobs, project_id, reason="init")

    topic_dir = workdir / "topic"
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "brief.md").write_bytes((_FIXTURE_DIR / "brief.md").read_bytes())

    finalize(engine, blobs, registry, project_id, "topic")

    return project_id
