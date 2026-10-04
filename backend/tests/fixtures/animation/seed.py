"""手工准备的"叙事已定稿"种子脚本（M2 T4，决策记录 D6）。

M3 的 narrative agent 还没实现，本计划（M2 动画阶段）的其余任务需要一个从
"叙事阶段已定稿"状态开始的项目才能测试。`seed_animation_project` 绕过真正
的 narrative agent：直接创建项目、把本目录下手工准备的 `narrative.json`/
`timing.json`/`audio/*.wav` 写进工作区的 `narrative/` 产物目录，再走
`stage_flow.finalize` 把 topic、narrative 两个阶段定稿，让 `animation`
阶段从 `locked` 变成 `active`。

`narrative/timing.json` 在真实流程里是"工具托管文件"（`NarrativeStage` 的
`write_scope().tool_managed`，agent 不能直接写），但这里是测试/开发环境下
的种子数据，不经过 agent 的写入路径，直接写工作区文件，不需要也不应该
套用 `WriteScope` 检查（`workspace/agent/conftest.py` 的 `StudioEnv.write`
是同样的做法：模拟"非 agent 写入"）。
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
_AUDIO_DIR = _FIXTURE_DIR / "audio"

_INITIAL_STAGES: tuple[tuple[str, str], ...] = (
    ("topic", "active"),
    ("narrative", "locked"),
    ("animation", "locked"),
)


def fixture_registry() -> StageRegistry:
    """一个只含三个占位阶段的 registry，只供本函数驱动 `stage_flow.finalize`
    使用（和 `main.create_app` 组装出的 registry 里的 `STAGE` 是同一批单例，
    不是另一份定义）。
    """
    registry = StageRegistry()
    for stage in (TOPIC_STAGE, NARRATIVE_STAGE, ANIMATION_STAGE):
        registry.register(stage)
    return registry


def _write_narrative_artifacts(workdir: Path) -> None:
    narrative_dir = workdir / "narrative"
    audio_dir = narrative_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    (narrative_dir / "narrative.json").write_bytes((_FIXTURE_DIR / "narrative.json").read_bytes())
    (narrative_dir / "timing.json").write_bytes((_FIXTURE_DIR / "timing.json").read_bytes())
    for wav_path in sorted(_AUDIO_DIR.glob("*.wav")):
        (audio_dir / wav_path.name).write_bytes(wav_path.read_bytes())


def seed_animation_project(engine: Engine, blobs: BlobStore, *, data_dir: Path) -> str:
    """建一个"叙事已定稿、动画阶段已解锁"的项目，返回 `project_id`。

    流程：建项目（同 `api.projects` 的初始化：`style/STYLE.md` 占位 + `init`
    快照）→ 定稿 topic（本 fixture 不需要真实选题内容，narrative 因此解锁为
    `active`）→ 把本目录下的手工 narrative fixture 写进工作区 → 定稿
    narrative（animation 因此从 `locked` 变 `active`）。
    """
    registry = fixture_registry()
    project = create_project(engine, id=uuid4().hex, title="动画阶段 fixture 项目")
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
