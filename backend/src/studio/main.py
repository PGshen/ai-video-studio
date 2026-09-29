"""api 进程入口：组装 FastAPI 应用（设计 §2.1；控制者裁定 1）。

`_lifespan` 按顺序完成：`migrate` → 种子模型配置 → 注册三个占位阶段定义 →
`RuntimeFactory`（总是注册 `claude`、`openai`，`enable_fake_runtime` 时注册 `fake`）→ `SessionBus` →
`TurnRunner` → `recover_on_startup`（设计 §4.4 第 8 步：把上次进程遗留的
`running`/`queued` turn 收尾为 `interrupted`）。这些单例挂在 `app.state`
上，`api/deps.py` 的依赖函数从这里取出，供 T8（会话/SSE）复用。关闭时先
`turn_runner.shutdown()`（运行中的 turn 收尾为 `interrupted`），再释放 engine。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from studio.agent import register_fake
from studio.agent.bus import SessionBus
from studio.agent.claude_runtime import register_claude
from studio.agent.openai_runtime import register_openai
from studio.agent.runner import TurnRunner
from studio.agent.runtime import RuntimeFactory
from studio.agent.stage import StageRegistry
from studio.api.animation import router as animation_router
from studio.api.blobs import router as blobs_router
from studio.api.files import router as files_router
from studio.api.ideas import router as ideas_router
from studio.api.jobs import router as jobs_router
from studio.api.profiles import router as profiles_router
from studio.api.projects import router as projects_router
from studio.api.sessions import router as sessions_router
from studio.api.snapshots import router as snapshots_router
from studio.config import Settings, get_settings
from studio.db.engine import make_engine, migrate
from studio.db.repo.profiles import seed_model_profiles
from studio.stages.animation import STAGE as ANIMATION_STAGE
from studio.stages.narrative import STAGE as NARRATIVE_STAGE
from studio.stages.topic import STAGE as TOPIC_STAGE
from studio.workspace import BlobStore


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    engine = make_engine(settings.data_dir / "studio.db")
    migrate(engine)
    seed_model_profiles(engine, enable_fake_runtime=settings.enable_fake_runtime, settings=settings)

    registry = StageRegistry()
    for stage in (TOPIC_STAGE, NARRATIVE_STAGE, ANIMATION_STAGE):
        registry.register(stage)

    runtime_factory = RuntimeFactory()
    register_claude(runtime_factory, settings)
    register_openai(runtime_factory, settings)
    if settings.enable_fake_runtime:
        register_fake(runtime_factory, delay_seconds=settings.fake_delay_seconds)

    bus = SessionBus()
    blobs = BlobStore(settings.data_dir / "blobs")
    turn_runner = TurnRunner(engine, blobs, registry, runtime_factory, bus, settings)
    turn_runner.recover_on_startup()

    app.state.engine = engine
    app.state.blobs = blobs
    app.state.registry = registry
    app.state.runtime_factory = runtime_factory
    app.state.bus = bus
    app.state.turn_runner = turn_runner

    try:
        yield
    finally:
        # Let running turns go through _finish (guard, partial snapshot, status
        # `interrupted`) before the engine goes away.
        try:
            await turn_runner.shutdown()
        finally:
            engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings if settings is not None else get_settings()

    app = FastAPI(title="ai-video-studio", lifespan=_lifespan)
    app.state.settings = resolved_settings
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=resolved_settings.allowed_hosts)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(projects_router)
    app.include_router(sessions_router)
    app.include_router(files_router)
    app.include_router(snapshots_router)
    app.include_router(profiles_router)
    app.include_router(jobs_router)
    app.include_router(animation_router)
    app.include_router(blobs_router)
    app.include_router(ideas_router)

    return app


app = create_app()
