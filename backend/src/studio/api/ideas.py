"""`/api/ideas`：选题池卡片（设计 §5.0；计划 M4 T2）。

卡片可以归档（`status=archived`，可恢复），也可以硬删除（`DELETE`，不可恢复）；已经创建过项目的
卡片不能删（409），避免项目指向一张不存在的卡片。一张卡片可以创建多个项目
（`POST /api/projects` 带 `idea_id`），关联记在项目上，卡片状态不变。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine

from studio.api.deps import get_engine
from studio.api.schemas import IdeaCreate, IdeaOut, IdeaUpdate
from studio.db.repo import ideas as repo
from studio.db.repo.ideas import IdeaValue
from studio.db.repo.projects import list_projects

router = APIRouter(prefix="/api", tags=["ideas"])


def _out(value: IdeaValue) -> IdeaOut:
    return IdeaOut(
        id=value.id,
        title=value.title,
        pitch=value.pitch,
        counterintuitive=value.counterintuitive,
        tags=value.tags,
        scores=value.scores,
        status=value.status,
        source_session_id=value.source_session_id,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, repo.IdeaNotFoundError):
        return HTTPException(status_code=404, detail=f"卡片不存在：{exc}")
    if isinstance(exc, repo.IdeaValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/ideas", response_model=list[IdeaOut])
def list_ideas_endpoint(
    status: Literal["idea", "archived", "all"] | None = None,
    engine: Engine = Depends(get_engine),
) -> list[IdeaOut]:
    return [_out(v) for v in repo.list_ideas(engine, status=status)]


@router.post("/ideas", response_model=IdeaOut, status_code=201)
def create_idea_endpoint(body: IdeaCreate, engine: Engine = Depends(get_engine)) -> IdeaOut:
    try:
        return _out(
            repo.create_idea(
                engine,
                title=body.title,
                pitch=body.pitch,
                counterintuitive=body.counterintuitive,
                tags=body.tags,
                scores=body.scores,
            )
        )
    except (repo.IdeaValidationError, repo.DuplicateIdeaError) as exc:
        raise _http_error(exc) from exc


@router.get("/ideas/{idea_id}", response_model=IdeaOut)
def get_idea_endpoint(idea_id: str, engine: Engine = Depends(get_engine)) -> IdeaOut:
    value = repo.get_idea(engine, idea_id)
    if value is None:
        raise HTTPException(status_code=404, detail=f"卡片不存在：{idea_id}")
    return _out(value)


@router.patch("/ideas/{idea_id}", response_model=IdeaOut)
def update_idea_endpoint(
    idea_id: str, body: IdeaUpdate, engine: Engine = Depends(get_engine)
) -> IdeaOut:
    provided = body.model_fields_set
    changes: dict[str, Any] = {name: getattr(body, name) for name in provided}
    if "title" in changes and changes["title"] is None:
        raise HTTPException(status_code=422, detail="标题不能为空")
    if "status" in changes and changes["status"] is None:
        raise HTTPException(status_code=422, detail="状态不能为空")
    for name in ("tags", "scores"):
        if name in changes and changes[name] is None:
            changes[name] = [] if name == "tags" else {}
    try:
        return _out(repo.update_idea(engine, idea_id, **changes))
    except (
        repo.IdeaNotFoundError,
        repo.IdeaValidationError,
        repo.DuplicateIdeaError,
    ) as exc:
        raise _http_error(exc) from exc


@router.delete("/ideas/{idea_id}", status_code=204)
def delete_idea_endpoint(idea_id: str, engine: Engine = Depends(get_engine)) -> Response:
    """硬删除一张卡片；已经有项目关联时 409，要先删掉这些项目。"""
    if repo.get_idea(engine, idea_id) is None:
        raise HTTPException(status_code=404, detail=f"卡片不存在：{idea_id}")
    linked = sum(1 for project in list_projects(engine) if project.idea_id == idea_id)
    if linked:
        raise HTTPException(
            status_code=409, detail=f"这张卡片已创建 {linked} 个项目，请先删除这些项目再删除卡片"
        )
    try:
        repo.delete_idea(engine, idea_id)
    except repo.IdeaNotFoundError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)
