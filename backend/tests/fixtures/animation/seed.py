"""老 manim 项目的种子（M2 T4 的 fixture，Manim 下线后改作只读老项目，ADR 0027）。

`fixtures/animation/` 下手工准备的 `narrative.json`/`timing.json`/`audio/*.wav` 同时是 HTML 讲解
等种子共用的叙事产物（`_write_narrative_artifacts`）。

`seed_legacy_manim_project` 建一个"没有类型字段"的老项目（按 `LEGACY_KIND` 解析为 Manim 讲解）：
定稿 topic 和 narrative，`animation` 阶段已不再注册，因此保持 `locked`。

`narrative/timing.json` 在真实流程里是"工具托管文件"，这里是测试种子数据，直接写工作区文件，
不经过 agent 的写入路径。
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine

from studio.agent.stage import StageRegistry
from studio.agent.stage_flow import finalize
from studio.db.repo.projects import create_project
from studio.db.repo.stages import create_stage
from studio.stages.narrative import STAGE as NARRATIVE_STAGE
from studio.stages.topic import STAGE as TOPIC_STAGE
from studio.workspace import BlobStore, create_snapshot, init_workspace

_FIXTURE_DIR = Path(__file__).parent
_AUDIO_DIR = _FIXTURE_DIR / "audio"

_INITIAL_STAGES: tuple[tuple[str, str], ...] = (
    ("topic", "active"),
    ("narrative", "locked"),
    ("animation", "locked"),
)


def _write_narrative_artifacts(workdir: Path) -> None:
    narrative_dir = workdir / "narrative"
    audio_dir = narrative_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    (narrative_dir / "narrative.json").write_bytes((_FIXTURE_DIR / "narrative.json").read_bytes())
    (narrative_dir / "timing.json").write_bytes((_FIXTURE_DIR / "timing.json").read_bytes())
    for wav_path in sorted(_AUDIO_DIR.glob("*.wav")):
        (audio_dir / wav_path.name).write_bytes(wav_path.read_bytes())


def seed_legacy_manim_project(engine: Engine, blobs: BlobStore, *, data_dir: Path) -> str:
    """建一个"叙事已定稿"的老 manim 项目，返回 `project_id`。"""
    registry = StageRegistry()
    for stage in (TOPIC_STAGE, NARRATIVE_STAGE):
        registry.register(stage)
    project = create_project(engine, id=uuid4().hex, title="老 manim 项目 fixture")
    project_id = project.id

    for stage, status in _INITIAL_STAGES:
        create_stage(engine, project_id=project_id, stage=stage, status=status)

    style = {"style/STYLE.md": "# 风格\n\n（fixture 占位）\n"}
    workdir = init_workspace(data_dir, project_id, style)
    create_snapshot(engine, blobs, project_id, reason="init")

    finalize(engine, blobs, registry, project_id, "topic")
    _write_narrative_artifacts(workdir)
    finalize(engine, blobs, registry, project_id, "narrative")

    return project_id
