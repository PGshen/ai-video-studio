from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_health_endpoint_returns_ok(tmp_path: Path) -> None:
    from studio.config import Settings
    from studio.main import create_app

    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
