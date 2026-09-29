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

项目级串行（I4）：凡是"先查 `is_project_busy` 再写工作区"的端点都写成
`async def`，在事件循环线程上执行，检查与写入之间不 `await`——`TurnRunner`
也在事件循环上改 `_running`、调度排队的 turn，两者不会交错。同步 `def` 端点
会跑在线程池里，出现检查通过后被调度器插队的竞态。代价是这些端点里的
短小同步 IO（SQLite、写文件、回滚）会占用事件循环片刻，单人本地可接受。
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine

from studio.agent.runner import TurnRunner
from studio.agent.stage import StageDefinition, StageRegistry
from studio.agent.stage_flow import StageFlowError, finalize, reopen
from studio.api.deps import get_blobs, get_engine, get_registry, get_settings, get_turn_runner
from studio.api.schemas import ProjectCreate, ProjectDetailOut, ProjectOut, StageOut
from studio.config import Settings
from studio.db.repo.ideas import (
    IdeaStateError,
    IdeaValue,
    get_idea,
    mark_picked,
)
from studio.db.repo.projects import (
    ProjectValue,
    clear_project_completed,
    create_project,
    delete_project,
    get_project,
    list_projects,
)
from studio.db.repo.snapshots import delete_snapshots
from studio.db.repo.stages import StageValue, create_stage, delete_stages, list_stages
from studio.workspace import (
    BlobStore,
    create_snapshot,
    init_workspace,
    project_dir,
    remove_workspace,
)

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
        completed_at=value.completed_at,
    )


def _stage_out(value: StageValue) -> StageOut:
    return StageOut(
        stage=value.stage,
        status=value.status,
        finalized_snapshot_id=value.finalized_snapshot_id,
        based_on_snapshot_id=value.based_on_snapshot_id,
        finalized_at=value.finalized_at,
    )


_SCORE_LABELS = (
    ("counterintuitive", "反直觉"),
    ("provable", "可论证"),
    ("visual", "可视化"),
    ("novelty", "新鲜度"),
)
IDEA_CARD_PATH = "topic/notes/idea-card.md"


def _idea_card_markdown(idea: IdeaValue) -> str:
    """想法卡片的 Markdown 形式，放进新项目的 `topic/notes/`，选题阶段 agent 先读它。"""
    lines = [f"# {idea.title}", "", "（来自选题池的想法卡片，是选题打磨的起点，不是结论。）", ""]
    lines += ["## 一句话卖点", "", idea.pitch or "（未填写）", ""]
    lines += ["## 反直觉点", "", idea.counterintuitive or "（未填写）", ""]
    lines += ["## 标签", "", "、".join(idea.tags) if idea.tags else "（无）", ""]
    scores = [
        f"- {label}：{idea.scores[key]}/5" for key, label in _SCORE_LABELS if key in idea.scores
    ]
    lines += ["## 评分（1–5）", "", *(scores or ["（未评分）"]), ""]
    return "\n".join(lines)


def _init_workspace(
    engine: Engine,
    blobs: BlobStore,
    settings: Settings,
    project_id: str,
    title: str,
    extra_files: dict[str, str] | None = None,
) -> None:
    style = f"# {title}\n\n（风格占位，风格库在 M5 实现）\n"
    init_workspace(settings.data_dir, project_id, {"style/STYLE.md": style, **(extra_files or {})})
    create_snapshot(engine, blobs, project_id, reason="init")


def _cleanup_failed_project(engine: Engine, settings: Settings, project_id: str) -> None:
    remove_workspace(settings.data_dir, project_id)
    delete_snapshots(engine, project_id)
    delete_stages(engine, project_id)
    delete_project(engine, project_id)


def _require_pickable_idea(engine: Engine, idea_id: str) -> IdeaValue:
    idea = get_idea(engine, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail=f"想法卡片不存在：{idea_id}")
    if idea.status != "idea":
        raise HTTPException(
            status_code=409, detail=f"这张卡片的状态是 {idea.status}，不能用来创建项目"
        )
    return idea


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project_endpoint(
    body: ProjectCreate,
    engine: Engine = Depends(get_engine),
    blobs: BlobStore = Depends(get_blobs),
    settings: Settings = Depends(get_settings),
) -> ProjectOut:
    idea = _require_pickable_idea(engine, body.idea_id) if body.idea_id is not None else None
    project_id = uuid4().hex
    try:
        _init_workspace(
            engine,
            blobs,
            settings,
            project_id,
            body.title,
            {IDEA_CARD_PATH: _idea_card_markdown(idea)} if idea is not None else None,
        )
        project = create_project(
            engine,
            id=project_id,
            title=body.title,
            idea_id=body.idea_id,
            settings=body.settings,
        )
        for stage, status in _INITIAL_STAGES:
            create_stage(engine, project_id=project_id, stage=stage, status=status)
        if idea is not None:
            # 最后一步，条件更新：两个请求同时用一张卡片时，输的一方在这里失败。
            mark_picked(engine, idea.id, project_id)
    except IdeaStateError as exc:
        _cleanup_failed_project(engine, settings, project_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
async def get_project_endpoint(
    project_id: str,
    engine: Engine = Depends(get_engine),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> ProjectDetailOut:
    project = _require_project(engine, project_id)
    stages = [_stage_out(s) for s in list_stages(engine, project_id)]
    busy = turn_runner.is_project_busy(project_id)
    return ProjectDetailOut(**_project_out(project).model_dump(), stages=stages, busy=busy)


def _require_stage_definition(stage: str, registry: StageRegistry) -> StageDefinition:
    try:
        return registry.get(stage)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"未知阶段：{stage}") from exc


def _require_not_busy(turn_runner: TurnRunner, project_id: str) -> None:
    if turn_runner.is_project_busy(project_id):
        raise HTTPException(status_code=409, detail="项目正在运行中的一轮，请稍后再试")


@router.post("/projects/{project_id}/stages/{stage}/finalize", response_model=StageOut)
async def finalize_stage_endpoint(
    project_id: str,
    stage: str,
    engine: Engine = Depends(get_engine),
    blobs: BlobStore = Depends(get_blobs),
    registry: StageRegistry = Depends(get_registry),
    turn_runner: TurnRunner = Depends(get_turn_runner),
    settings: Settings = Depends(get_settings),
) -> StageOut:
    _require_project(engine, project_id)
    definition = _require_stage_definition(stage, registry)
    _require_not_busy(turn_runner, project_id)
    blockers = definition.finalize_blockers(project_dir(settings.data_dir, project_id))
    if blockers:
        raise HTTPException(status_code=409, detail="暂时不能定稿：" + "；".join(blockers))
    try:
        value = finalize(engine, blobs, registry, project_id, stage)
    except StageFlowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _stage_out(value)


@router.post("/projects/{project_id}/stages/{stage}/reopen", response_model=StageOut)
async def reopen_stage_endpoint(
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
    if stage == "animation":
        # `completed_at`（`api.animation.finalize_render_endpoint` 设置）代表
        # "成片已经和工作区一致地定稿过"；重新打开动画阶段后工作区又能改，
        # 成片不再代表当前状态，这条"已完成"的标记要跟着撤销（评审发现）。
        clear_project_completed(engine, project_id)
    return _stage_out(value)
