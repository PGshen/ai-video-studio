"""`POST /api/projects/{id}/animation/finalize-render`（任务简报 T11）。

用户"成片定稿"：`output/final.json`（worker 直接写在工作区顶层的产物，见
`worker.py` T5 决策记录 D20）记录了它渲染时读到的 `snapshot_id`；只有这个
值等于项目当前最新快照时才允许定稿——不等说明渲染之后工作区又有改动没有
被纳入这次成片，需要用户重新渲染。一致时复用 `api.projects.finalize_stage_endpoint`
已经在用的 `stage_flow.finalize`（D4 的延伸：一次事实来源，不给"阶段怎么
定稿"搞两份实现），并把项目标记完成。

读 `output/final.json` 直接用 `pathlib`，不走 `workspace.files.read_text`
——`output/` 是 `workspace.layout.HIDDEN_TOP_DIRS` 之一，`read_text` 对隐藏
顶层目录会主动抛 `ScopeError`（这层"对 agent/前端隐藏"的限制是给 agent 工具
和文件浏览 api 用的；本端点和 T10 的 `download_final_video_endpoint` 一样是
在读 worker 产物，不受这层限制，两者用同一种直接读工作区文件的方式）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from studio.agent.runner import TurnRunner
from studio.agent.stage import StageRegistry
from studio.agent.stage_flow import StageFlowError, finalize
from studio.api.animation_stage import require_live_animation_stage
from studio.api.deps import get_blobs, get_engine, get_registry, get_settings, get_turn_runner
from studio.api.scene_checks import compute_scene_checks
from studio.api.schemas import SceneCheckOut, SceneChecksOut, SceneChecksResponse, StageOut
from studio.config import Settings
from studio.db.repo.projects import get_project, mark_project_completed
from studio.db.repo.snapshots import latest_snapshot
from studio.db.repo.stages import StageValue
from studio.workspace import BlobStore, project_dir

router = APIRouter(prefix="/api", tags=["animation"])


def _require_project(engine: Engine, project_id: str) -> None:
    if get_project(engine, project_id) is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")


def _require_not_busy(turn_runner: TurnRunner, project_id: str) -> None:
    if turn_runner.is_project_busy(project_id):
        raise HTTPException(status_code=409, detail="项目正在运行中的一轮，请稍后再试")


def _stage_out(value: StageValue) -> StageOut:
    return StageOut(
        stage=value.stage,
        status=value.status,
        finalized_snapshot_id=value.finalized_snapshot_id,
        based_on=value.based_on,
        finalized_at=value.finalized_at,
    )


def _read_rendered_snapshot_id(settings: Settings, project_id: str) -> str:
    workdir = project_dir(settings.data_dir, project_id)
    final_json_path = workdir / "output" / "final.json"
    if not final_json_path.is_file():
        raise HTTPException(status_code=404, detail="成片尚未渲染完成，无法定稿")
    final_meta = json.loads(final_json_path.read_text(encoding="utf-8"))
    return final_meta["snapshot_id"]


@router.post("/projects/{project_id}/animation/finalize-render", response_model=StageOut)
async def finalize_render_endpoint(
    project_id: str,
    engine: Engine = Depends(get_engine),
    blobs: BlobStore = Depends(get_blobs),
    registry: StageRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> StageOut:
    _require_project(engine, project_id)
    _require_not_busy(turn_runner, project_id)
    stage_name = require_live_animation_stage(engine, project_id)

    rendered_snapshot_id = _read_rendered_snapshot_id(settings, project_id)
    current = latest_snapshot(engine, project_id)
    if current is None or current.id != rendered_snapshot_id:
        raise HTTPException(status_code=409, detail="工作区有未纳入成片的改动，请重新渲染")

    try:
        stage = finalize(engine, blobs, registry, project_id, stage_name)
    except StageFlowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    mark_project_completed(engine, project_id)
    return _stage_out(stage)


@router.get("/projects/{project_id}/animation/scene-checks", response_model=SceneChecksResponse)
def get_scene_checks_endpoint(
    project_id: str,
    scene_id: list[str] = Query(default=[]),
    engine: Engine = Depends(get_engine),
) -> SceneChecksResponse:
    _require_project(engine, project_id)
    checks = compute_scene_checks(engine, project_id, scene_id)
    return SceneChecksResponse(
        scenes={
            sid: SceneChecksOut(
                validate_scenes=SceneCheckOut(
                    status=checks[sid].validate_scenes.status,
                    stale=checks[sid].validate_scenes.stale,
                    checked_at=checks[sid].validate_scenes.checked_at,
                    images=list(checks[sid].validate_scenes.images),
                ),
                render_preview=SceneCheckOut(
                    status=checks[sid].render_preview.status,
                    stale=checks[sid].render_preview.stale,
                    checked_at=checks[sid].render_preview.checked_at,
                    images=list(checks[sid].render_preview.images),
                ),
            )
            for sid in scene_id
        }
    )
