"""api 进程入口：组装 FastAPI 应用。"""

from __future__ import annotations

from fastapi import FastAPI

from studio.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings if settings is not None else get_settings()

    app = FastAPI(title="ai-video-studio")
    app.state.settings = resolved_settings

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
