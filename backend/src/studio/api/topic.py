"""`GET /api/projects/{id}/topic/check`（计划 M4 T6）：选题简报的结构检查。

和 `check_brief` 工具共用 `stages.topic.brief.check_workspace`，画布用它显示提示条。
简报不存在不是 404（项目存在，只是还没写），而是 `ok=false` 加一条错误。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine

from studio.api.deps import get_engine, get_settings
from studio.api.schemas import TopicCheckOut
from studio.config import Settings
from studio.db.repo.projects import get_project
from studio.stages.topic.brief import check_workspace
from studio.workspace import project_dir

router = APIRouter(prefix="/api", tags=["topic"])


@router.get("/projects/{project_id}/topic/check", response_model=TopicCheckOut)
def check_topic_endpoint(
    project_id: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> TopicCheckOut:
    if get_project(engine, project_id) is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")
    result = check_workspace(project_dir(settings.data_dir, project_id))
    return TopicCheckOut(ok=result.ok, errors=result.errors, warnings=result.warnings)
