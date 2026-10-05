"""Projects for the synth-music flows (3A T9): a motion reel and an explainer with a background bed.

Same approach as `fixtures.animation_html.seed`: stage rows follow the project pipeline, upstream
stages are finalised from fixture artifacts so the stage under test is unlocked.
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
from studio.stages.beatsheet import STAGE as BEATSHEET_STAGE
from studio.stages.concept import STAGE as CONCEPT_STAGE
from studio.stages.music import STAGE as MUSIC_STAGE
from studio.stages.narrative import STAGE as NARRATIVE_STAGE
from studio.stages.topic import STAGE as TOPIC_STAGE
from studio.workspace import BlobStore, create_snapshot, init_workspace

REEL_PIPELINE = ["concept", "beatsheet", "music", "animation_html"]
BED_PIPELINE = ["topic", "narrative", "music", "animation_html"]

BRIEF = "\n".join(
    f"## {name}\n\n{body}\n"
    for name, body in [
        ("主题", "一个点的裂变与回收"),
        ("目标时长", "12 秒"),
        ("情绪与能量走向", "低 → 顶点"),
        ("视觉母题", "白色圆点与方形轨道"),
        ("参考与灵感", "动态图形短片"),
        ("段落草图", "两段：蓄力与释放"),
        ("风险点", "节奏容易散，靠网格约束"),
    ]
)

BEATSHEET = """{
  "bpm": 128,
  "sections": [
    {"id": "s1", "label": "BUILD", "bars": 3, "intent": "蓄力", "energy": "low",
     "moments": [{"at": "1.1", "visual_action": "圆点呼吸"}]},
    {"id": "s2", "label": "DROP", "bars": 3, "intent": "释放", "energy": "peak",
     "moments": [{"at": "1.1", "visual_action": "炸开"}, {"at": "2.3", "visual_action": "回收"}]}
  ]
}
"""

# Time comes only from env.bt / env.hit: the shift check and the retiming check both rely on it.
REEL_SCENE = """
module.exports = { draw(ctx, lt, env) {
  ctx.fillStyle = '#102030'; ctx.fillRect(0, 0, env.W, env.H);
  ctx.fillStyle = '#fff';
  ctx.fillRect(100 + 40 * env.bt(1), 100, 200 + 600 * env.hit('kick'), 120);
} };
"""


def registry() -> StageRegistry:
    registry = StageRegistry()
    for stage in (
        TOPIC_STAGE,
        NARRATIVE_STAGE,
        CONCEPT_STAGE,
        BEATSHEET_STAGE,
        MUSIC_STAGE,
        ANIMATION_HTML_STAGE,
    ):
        registry.register(stage)
    return registry


def _create(engine: Engine, blobs: BlobStore, data_dir: Path, settings: dict, pipeline: list[str]):
    project = create_project(
        engine, id=uuid4().hex, title="合成配乐 fixture 项目", settings=settings
    )
    for index, stage in enumerate(pipeline):
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
    return project.id, workdir


def seed_reel_project(engine: Engine, blobs: BlobStore, *, data_dir: Path) -> str:
    """`concept` is the active stage; everything after it is locked."""
    settings = {
        "video_kind": "motion_reel",
        "engine": "html",
        "narration": False,
        "music_source": "synth",
        "pipeline": REEL_PIPELINE,
    }
    return _create(engine, blobs, data_dir, settings, REEL_PIPELINE)[0]


def seed_bed_project(engine: Engine, blobs: BlobStore, *, data_dir: Path) -> str:
    """Narrative finalised, `music` is the active stage."""
    settings = {
        "video_kind": "explainer_html",
        "engine": "html",
        "narration": True,
        "music_source": "synth",
        "pipeline": BED_PIPELINE,
    }
    pid, workdir = _create(engine, blobs, data_dir, settings, BED_PIPELINE)
    reg = registry()
    finalize(engine, blobs, reg, pid, "topic")
    _write_narrative_artifacts(workdir)
    finalize(engine, blobs, reg, pid, "narrative")
    return pid
