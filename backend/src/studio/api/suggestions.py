"""回退建议接口（设计 §5.4；计划 M5 T9）。

- `GET /api/projects/{id}/suggestions?status=`：项目的建议，按创建时间升序；
- `GET /api/projects/{id}/suggestions/summary`：`{目标阶段: 待处理数量}`，阶段导航角标用；
- `POST /api/suggestions/{id}/apply|dismiss`：把 `open` 的建议标为已处理/已忽略，重复处理 409。

建议由下游阶段的 agent 经 `suggest_upstream_change` 工具写入（`stages/common`），产生时会给会话
发 `suggestion` 事件；这里只负责读取和状态流转。「去处理」的跳转和预填在前端做。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine

from studio.api.deps import get_engine
from studio.api.schemas import SuggestionOut
from studio.db.repo.projects import get_project
from studio.db.repo.suggestions import (
    SuggestionStateError,
    SuggestionValue,
    count_open_by_target_stage,
    list_suggestions,
    resolve_suggestion,
)

router = APIRouter(prefix="/api", tags=["suggestions"])


def _out(value: SuggestionValue) -> SuggestionOut:
    return SuggestionOut(
        id=value.id,
        project_id=value.project_id,
        from_stage=value.from_stage,
        to_stage=value.to_stage,
        content=value.content,
        status=value.status,
        turn_id=value.turn_id,
        created_at=value.created_at,
    )


def _require_project(engine: Engine, project_id: str) -> None:
    if get_project(engine, project_id) is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")


@router.get("/projects/{project_id}/suggestions", response_model=list[SuggestionOut])
def list_suggestions_endpoint(
    project_id: str,
    status: Literal["open", "applied", "dismissed"] | None = None,
    engine: Engine = Depends(get_engine),
) -> list[SuggestionOut]:
    _require_project(engine, project_id)
    return [_out(v) for v in list_suggestions(engine, project_id, status)]


@router.get("/projects/{project_id}/suggestions/summary", response_model=dict[str, int])
def suggestions_summary_endpoint(
    project_id: str, engine: Engine = Depends(get_engine)
) -> dict[str, int]:
    _require_project(engine, project_id)
    return count_open_by_target_stage(engine, project_id)


def _resolve(engine: Engine, suggestion_id: str, status: str) -> SuggestionOut:
    try:
        return _out(resolve_suggestion(engine, suggestion_id, status))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"建议不存在：{suggestion_id}") from exc
    except SuggestionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/suggestions/{suggestion_id}/apply", response_model=SuggestionOut)
def apply_suggestion_endpoint(
    suggestion_id: str, engine: Engine = Depends(get_engine)
) -> SuggestionOut:
    return _resolve(engine, suggestion_id, "applied")


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=SuggestionOut)
def dismiss_suggestion_endpoint(
    suggestion_id: str, engine: Engine = Depends(get_engine)
) -> SuggestionOut:
    return _resolve(engine, suggestion_id, "dismissed")
