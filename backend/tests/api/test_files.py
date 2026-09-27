"""`/api/projects/{id}/files*`（任务简报 T7；评审关注点 3）。"""

from __future__ import annotations

from .conftest import ApiEnv, assert_detail


async def _project(api_env: ApiEnv) -> str:
    body = await api_env.create_project()
    return body["id"]


class TestListFiles:
    async def test_hides_cache_and_output_marks_upstream_readonly(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        workdir = api_env.workdir(pid)
        (workdir / ".cache").mkdir(parents=True, exist_ok=True)
        (workdir / ".cache" / "tmp.txt").write_text("x", encoding="utf-8")
        (workdir / "output").mkdir(parents=True, exist_ok=True)
        (workdir / "output" / "final.mp4").write_bytes(b"\x00")
        (workdir / "upstream" / "topic").mkdir(parents=True, exist_ok=True)
        (workdir / "upstream" / "topic" / "brief.md").write_text("v1", encoding="utf-8")

        response = await api_env.client.get(f"/api/projects/{pid}/files")

        assert response.status_code == 200
        entries = {e["path"]: e["readonly"] for e in response.json()["files"]}
        assert "style/STYLE.md" in entries and entries["style/STYLE.md"] is False
        assert "upstream/topic/brief.md" in entries
        assert entries["upstream/topic/brief.md"] is True
        assert not any(p.startswith(".cache/") for p in entries)
        assert not any(p.startswith("output/") for p in entries)

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/projects/does-not-exist/files")
        assert response.status_code == 404


class TestReadFile:
    async def test_reads_text_file(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.get(f"/api/projects/{pid}/files/style/STYLE.md")

        assert response.status_code == 200
        assert "text/markdown" in response.headers["content-type"]
        assert response.text.startswith("#")

    async def test_reads_binary_file_with_generic_content_type(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        workdir = api_env.workdir(pid)
        (workdir / "topic").mkdir(parents=True, exist_ok=True)
        payload = bytes([0x89, 0x50, 0x4E, 0x47, 0x00, 0x01, 0x02])
        (workdir / "topic" / "logo.png").write_bytes(payload)

        response = await api_env.client.get(f"/api/projects/{pid}/files/topic/logo.png")

        assert response.status_code == 200
        assert response.content == payload
        assert response.headers["content-type"] == "image/png"

    async def test_invalid_path_is_400(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        # ".." percent-encoded so httpx does not collapse it client-side before
        # the request is even sent (a literal ".." in the URL gets normalized
        # away by the HTTP client, which would defeat the point of this test).
        response = await api_env.client.get(f"/api/projects/{pid}/files/%2e%2e/secrets.txt")

        assert response.status_code == 400
        assert_detail(response)

    async def test_symlink_is_rejected_with_400(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        workdir = api_env.workdir(pid)
        (workdir / "topic").mkdir(parents=True, exist_ok=True)
        target = workdir / "style" / "STYLE.md"
        link = workdir / "topic" / "sneaky.md"
        link.symlink_to(target)

        response = await api_env.client.get(f"/api/projects/{pid}/files/topic/sneaky.md")

        assert response.status_code == 400
        assert_detail(response)

    async def test_file_under_cache_is_404(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        workdir = api_env.workdir(pid)
        (workdir / ".cache").mkdir(parents=True, exist_ok=True)
        (workdir / ".cache" / "tmp.txt").write_text("x", encoding="utf-8")

        response = await api_env.client.get(f"/api/projects/{pid}/files/.cache/tmp.txt")

        assert response.status_code == 404

    async def test_missing_file_is_404(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.get(f"/api/projects/{pid}/files/topic/nope.md")

        assert response.status_code == 404


class TestWriteFile:
    async def test_writes_within_scope(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.put(
            f"/api/projects/{pid}/files/topic/brief.md",
            params={"stage": "topic"},
            json={"content": "新简报"},
        )

        assert response.status_code == 200
        assert (api_env.workdir(pid) / "topic" / "brief.md").read_text(encoding="utf-8") == "新简报"

    async def test_out_of_scope_is_403(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.put(
            f"/api/projects/{pid}/files/narrative/narrative.json",
            params={"stage": "topic"},
            json={"content": "{}"},
        )

        assert response.status_code == 403
        assert_detail(response)

    async def test_write_into_upstream_is_403(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.put(
            f"/api/projects/{pid}/files/upstream/topic/brief.md",
            params={"stage": "narrative"},
            json={"content": "改写"},
        )

        assert response.status_code == 403

    async def test_tool_managed_file_is_403_even_though_dir_is_writable(
        self, api_env: ApiEnv
    ) -> None:
        pid = await _project(api_env)

        response = await api_env.client.put(
            f"/api/projects/{pid}/files/narrative/timing.json",
            params={"stage": "narrative"},
            json={"content": "{}"},
        )

        assert response.status_code == 403

    async def test_invalid_path_is_400(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.put(
            f"/api/projects/{pid}/files/%2e%2e/evil.md",
            params={"stage": "topic"},
            json={"content": "x"},
        )

        assert response.status_code == 400

    async def test_unknown_stage_is_404(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.put(
            f"/api/projects/{pid}/files/topic/brief.md",
            params={"stage": "no-such-stage"},
            json={"content": "x"},
        )

        assert response.status_code == 404

    async def test_busy_project_is_409(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        turn_id = await api_env.make_busy(pid)

        response = await api_env.client.put(
            f"/api/projects/{pid}/files/topic/brief.md",
            params={"stage": "topic"},
            json={"content": "x"},
        )

        assert response.status_code == 409
        await api_env.release_busy(turn_id)
