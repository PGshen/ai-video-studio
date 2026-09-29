"""`GET /api/projects/{id}/blobs/{sha256}`（TD-21）：把工具结果里持久化到
blob 库的图片字节读出来给前端渲染缩略图（`agent/turn_events.py::_persist_image`）。
"""

from __future__ import annotations

from .conftest import ApiEnv


async def _project(api_env: ApiEnv) -> str:
    body = await api_env.create_project()
    return body["id"]


class TestGetBlob:
    async def test_returns_bytes_with_sniffed_media_type(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
        sha256 = api_env.app.state.blobs.put(png_bytes)

        response = await api_env.client.get(f"/api/projects/{pid}/blobs/{sha256}")

        assert response.status_code == 200
        assert response.content == png_bytes
        assert response.headers["content-type"] == "image/png"

    async def test_unknown_sha256_is_404(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.get(f"/api/projects/{pid}/blobs/" + "0" * 64)

        assert response.status_code == 404

    async def test_unknown_project_returns_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/projects/does-not-exist/blobs/" + "0" * 64)

        assert response.status_code == 404

    async def test_unrecognized_bytes_fall_back_to_octet_stream(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        sha256 = api_env.app.state.blobs.put(b"not an image")

        response = await api_env.client.get(f"/api/projects/{pid}/blobs/{sha256}")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
