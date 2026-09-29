"""`/api/brainstorm/sessions`：没有项目的头脑风暴会话（设计 §5.0；计划 M4 T3）。

会话的 `messages`/`cancel`/`continue`/`stream` 复用 `/api/sessions/{id}/*`（它们只按
会话 id 查，与项目无关）；这里只负责创建和列出。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine

from studio.agent.runtime import RuntimeFactory
from studio.api.deps import get_engine, get_runtime_factory
from studio.api.schemas import SessionCreate, SessionOut
from studio.api.sessions import session_out
from studio.db.repo.profiles import get_model_profile_by_id
from studio.db.repo.sessions import create_session, list_sessions

router = APIRouter(prefix="/api", tags=["brainstorm"])

_STAGE = "brainstorm"


@router.post("/brainstorm/sessions", response_model=SessionOut, status_code=201)
def create_brainstorm_session_endpoint(
    body: SessionCreate,
    engine: Engine = Depends(get_engine),
    runtime_factory: RuntimeFactory = Depends(get_runtime_factory),
) -> SessionOut:
    profile = get_model_profile_by_id(engine, body.model_profile_id)
    if profile is None:
        raise HTTPException(status_code=400, detail=f"模型配置不存在：{body.model_profile_id}")
    if not runtime_factory.has(profile.runtime):
        raise HTTPException(status_code=400, detail=f"运行时未启用：{profile.runtime}")
    session = create_session(
        engine,
        project_id=None,
        stage=_STAGE,
        model_profile_id=profile.id,
        runtime=profile.runtime,
    )
    return session_out(session)


@router.get("/brainstorm/sessions", response_model=list[SessionOut])
def list_brainstorm_sessions_endpoint(engine: Engine = Depends(get_engine)) -> list[SessionOut]:
    return [session_out(s) for s in list_sessions(engine, None, _STAGE)]
