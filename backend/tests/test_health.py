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
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_untrusted_host_header_is_rejected(tmp_path: Path) -> None:
    """M9: DNS rebinding — a page on evil.example resolving to 127.0.0.1 sends its own Host."""
    from studio.config import Settings
    from studio.main import create_app

    app = create_app(Settings(data_dir=tmp_path / "data"))

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            evil = await client.get("/api/health", headers={"host": "evil.example"})
            evil_port = await client.get("/api/health", headers={"host": "evil.example:8000"})
            local = await client.get("/api/health", headers={"host": "localhost:8000"})
            loopback = await client.get("/api/health")

    assert evil.status_code == 400
    assert evil_port.status_code == 400
    assert local.status_code == 200
    assert loopback.status_code == 200
