from __future__ import annotations

from pathlib import Path

from httpx import ASGITransport, AsyncClient


async def test_health_endpoint_returns_ok(tmp_path: Path) -> None:
    from studio.config import Settings
    from studio.main import create_app

    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
