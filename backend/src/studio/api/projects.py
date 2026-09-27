"""`/api/projects` 与阶段定稿/重新打开（任务简报 T7）。

项目创建的顺序（控制者裁定 5：失败不能留下"半成品"项目）：
1. 生成 project id（不经数据库，`create_project` 支持显式传入 id，见
   `db.repo.projects`），先把工作区文件（`style/STYLE.md`）和 `init` 快照
   建好——这一步失败时数据库还没有任何这个项目的行，`GET /projects` 天然
   看不到它。
2. 再插入 `projects` 行和三条 `project_stages` 行。这一步失败时（理论上
   只有数据库故障之类的极端情况）用 `except` 兜底清理：删工作区目录、删
   可能已经插入的 `snapshots`（含步骤 1 建的 `init` 快照行）/`projects`/
   `project_stages` 行，再把错误转成 500。`BlobStore` 里的内容不用清理：
   blob 是内容寻址、可能被其他项目共用，孤儿内容不影响正确性，也没有
   项目 id 可以定位删除。

"""

from __future__ import annotations

import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine

from studio.agent.runner import TurnRunner
from studio.agent.stage import StageDefinition, StageRegistry
from studio.agent.stage_flow import StageFlowError, finalize, reopen
from studio.api.deps import get_blobs, get_engine, get_registry, get_settings, get_turn_runner
from studio.api.schemas import ProjectCreate, ProjectDetailOut, ProjectOut, StageOut
from studio.config import Settings
from studio.db.repo.projects import (
    ProjectValue,
    create_project,
    delete_project,
    get_project,
    list_projects,
)
from studio.db.repo.snapshots import delete_snapshots
from studio.db.repo.stages import StageValue, create_stage, delete_stages, list_stages
from studio.workspace import BlobStore, create_snapshot, project_dir

router = APIRouter(prefix="/api", tags=["projects"])

_INITIAL_STAGES: tuple[tuple[str, str], ...] = (
    ("topic", "active"),
    ("narrative", "locked"),
    ("animation", "locked"),
)


def _project_out(value: ProjectValue) -> ProjectOut:
    return ProjectOut(
        id=value.id,
        title=value.title,
        idea_id=value.idea_id,
        current_stage=value.current_stage,
        settings=value.settings,
    )


def _stage_out(value: StageValue) -> StageOut:
    return StageOut(
        stage=value.stage,
        status=value.status,
        finalized_snapshot_id=value.finalized_snapshot_id,
        based_on_snapshot_id=value.based_on_snapshot_id,
        finalized_at=value.finalized_at,
    )


def _init_workspace(
    engine: Engine, blobs: BlobStore, settings: Settings, project_id: str, title: str
) -> None:
    workdir = project_dir(settings.data_dir, project_id)
    style_path = workdir / "style" / "STYLE.md"
    style_path.parent.mkdir(parents=True, exist_ok=True)
    style_path.write_text(f"# {title}\n\n（风格占位，风格库在 M5 实现）\n", encoding="utf-8")
    create_snapshot(engine, blobs, project_id, reason="init")


def _cleanup_failed_project(engine: Engine, settings: Settings, project_id: str) -> None:
    shutil.rmtree(project_dir(settings.data_dir, project_id), ignore_errors=True)
    delete_snapshots(engine, project_id)
    delete_stages(engine, project_id)
    delete_project(engine, project_id)


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project_endpoint(
    body: ProjectCreate,
    engine: Engine = Depends(get_engine),
    blobs: BlobStore = Depends(get_blobs),
    settings: Settings = Depends(get_settings),
) -> ProjectOut:
    project_id = uuid4().hex
    try:
        _init_workspace(engine, blobs, settings, project_id, body.title)
        project = create_project(engine, id=project_id, title=body.title, settings=body.settings)
        for stage, status in _INITIAL_STAGES:
            create_stage(engine, project_id=project_id, stage=stage, status=status)
    except Exception as exc:
        _cleanup_failed_project(engine, settings, project_id)
        raise HTTPException(status_code=500, detail=f"创建项目失败：{exc}") from exc
    return _project_out(project)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects_endpoint(engine: Engine = Depends(get_engine)) -> list[ProjectOut]:
    return [_project_out(p) for p in list_projects(engine)]


def _require_project(engine: Engine, project_id: str) -> ProjectValue:
    project = get_project(engine, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")
    return project


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
def get_project_endpoint(project_id: str, engine: Engine = Depends(get_engine)) -> ProjectDetailOut:
    project = _require_project(engine, project_id)
    stages = [_stage_out(s) for s in list_stages(engine, project_id)]
    return ProjectDetailOut(**_project_out(project).model_dump(), stages=stages)


def _require_stage_definition(stage: str, registry: StageRegistry) -> StageDefinition:
    try:
        return registry.get(stage)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"未知阶段：{stage}") from exc


def _require_not_busy(turn_runner: TurnRunner, project_id: str) -> None:
    if turn_runner.is_project_busy(project_id):
        raise HTTPException(status_code=409, detail="项目正在运行中的一轮，请稍后再试")


@router.post("/projects/{project_id}/stages/{stage}/finalize", response_model=StageOut)
def finalize_stage_endpoint(
    project_id: str,
    stage: str,
    engine: Engine = Depends(get_engine),
    blobs: BlobStore = Depends(get_blobs),
    registry: StageRegistry = Depends(get_registry),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> StageOut:
    _require_project(engine, project_id)
    _require_stage_definition(stage, registry)
    _require_not_busy(turn_runner, project_id)
    try:
        value = finalize(engine, blobs, registry, project_id, stage)
    except StageFlowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _stage_out(value)


@router.post("/projects/{project_id}/stages/{stage}/reopen", response_model=StageOut)
def reopen_stage_endpoint(
    project_id: str,
    stage: str,
    engine: Engine = Depends(get_engine),
    registry: StageRegistry = Depends(get_registry),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> StageOut:
    _require_project(engine, project_id)
    _require_stage_definition(stage, registry)
    _require_not_busy(turn_runner, project_id)
    try:
        value = reopen(engine, project_id, stage)
    except StageFlowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _stage_out(value)
