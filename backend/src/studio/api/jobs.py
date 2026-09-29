"""`/api/projects/{id}/render`、`.../jobs/{job_id}`、`.../jobs/latest`、
`.../output/final.mp4`（任务简报 T10；`.../jobs/latest` 是 TD-34 补的）。

- **创建渲染任务**：只检查动画阶段状态不是 `locked`，不重复跑 `validate_scenes`
  的校验逻辑（决策记录 D4：避免和 agent 工具的校验产生两份实现，未校验直接
  渲染的后果由 worker 渲染失败时的错误信息兜底）。`payload` 目前不需要放
  任何内容——worker 只靠 `JobValue.project_id` 定位项目（决策记录 D21），
  这个口子留给以后（比如记录创建任务时的快照 id）再用。
- **查询任务**：薄薄一层转发 `studio.jobs.get_job`，供前端每秒轮询（design
  §7）；任务不属于该项目时视为不存在，不泄露别的项目的任务信息。
- **查询最近一次任务**（TD-34）：`FinalRenderPanel.vue` 挂载时用它恢复
  `currentJobId`，不用等用户重新点一次"渲染成片"才看到上一次的进度/成片；
  没有任何任务时返回 `null`，不是 404——"这个项目还没渲染过"是正常状态，
  不是错误。
- **下载成片**：直接看 `data/projects/<id>/output/final.mp4` 是否存在——不
  额外检查 job 状态是不是 `done`，文件是否存在就是唯一事实来源，避免和
  "任务状态"产生第二份关于"成片是否已经渲染好"的判断逻辑。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import Engine

from studio.api.deps import get_engine, get_settings
from studio.api.schemas import JobOut
from studio.config import Settings
from studio.db.repo.projects import get_project
from studio.db.repo.stages import get_stage
from studio.jobs import JobValue, create_job, get_job, list_jobs
from studio.workspace import project_dir

router = APIRouter(prefix="/api", tags=["jobs"])

_RENDER_JOB_TYPE = "final_render"
_ANIMATION_STAGE = "animation"


def _require_project(engine: Engine, project_id: str) -> None:
    if get_project(engine, project_id) is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")


def _job_out(value: JobValue) -> JobOut:
    return JobOut(
        id=value.id,
        type=value.type,
        project_id=value.project_id,
        status=value.status,
        progress=value.progress,
        error=value.error,
        result=value.result,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


@router.post("/projects/{project_id}/render", response_model=JobOut, status_code=201)
def create_render_job_endpoint(project_id: str, engine: Engine = Depends(get_engine)) -> JobOut:
    _require_project(engine, project_id)
    stage = get_stage(engine, project_id, _ANIMATION_STAGE)
    if stage is None:
        raise HTTPException(status_code=404, detail="项目没有动画阶段")
    if stage.status == "locked":
        raise HTTPException(status_code=409, detail="动画阶段尚未解锁，不能创建渲染任务")
    job = create_job(engine, type=_RENDER_JOB_TYPE, project_id=project_id)
    return _job_out(job)


@router.get("/projects/{project_id}/jobs/latest", response_model=JobOut | None)
def get_latest_job_endpoint(
    project_id: str, type: str, engine: Engine = Depends(get_engine)
) -> JobOut | None:
    """项目最近一次某类型任务（TD-34）：`FinalRenderPanel.vue` 挂载时用它
    恢复 `currentJobId`，不用等用户重新点一次"渲染成片"才看到进度。声明在
    `/jobs/{job_id}` 之前——否则 FastAPI 按注册顺序匹配，`job_id="latest"`
    会先命中那条路由。
    """
    _require_project(engine, project_id)
    jobs = list_jobs(engine, project_id, type=type)
    return _job_out(jobs[-1]) if jobs else None


@router.get("/projects/{project_id}/jobs/{job_id}", response_model=JobOut)
def get_job_endpoint(project_id: str, job_id: str, engine: Engine = Depends(get_engine)) -> JobOut:
    _require_project(engine, project_id)
    job = get_job(engine, job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"任务不存在：{job_id}")
    return _job_out(job)


@router.get("/projects/{project_id}/output/final.mp4")
def download_final_video_endpoint(
    project_id: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    _require_project(engine, project_id)
    workdir = project_dir(settings.data_dir, project_id)
    final_path = workdir / "output" / "final.mp4"
    if not final_path.is_file():
        raise HTTPException(status_code=404, detail="成片尚未渲染完成")
    return FileResponse(final_path, media_type="video/mp4", filename="final.mp4")
