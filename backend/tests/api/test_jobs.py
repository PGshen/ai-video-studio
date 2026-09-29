"""`/api/projects/{id}/render`、`.../jobs/{job_id}`、`.../output/final.mp4`（任务简报 T10）。

创建渲染任务只检查动画阶段状态不是 `locked`（决策记录 D4），不重复跑
`validate_scenes` 的校验逻辑；成片下载端点只看 `output/final.mp4` 是否存在，
不检查 job 状态（同样是"不重复一份判断逻辑"的思路，文件是否存在就是唯一
事实来源）。
"""

from __future__ import annotations

from fixtures.animation.seed import seed_animation_project

from .conftest import ApiEnv, assert_detail


async def _locked_project(api_env: ApiEnv) -> str:
    """一个刚创建的项目：动画阶段还是 `locked`（`_INITIAL_STAGES` 的默认值）。"""
    body = await api_env.create_project()
    return body["id"]


async def _animation_project(api_env: ApiEnv) -> str:
    """叙事已定稿、动画阶段 `active` 的项目（复用 T4 的种子脚本，绕过 M3）。"""
    return seed_animation_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )


class TestCreateRenderJob:
    async def test_creates_queued_job_for_active_animation_stage(self, api_env: ApiEnv) -> None:
        pid = await _animation_project(api_env)

        response = await api_env.client.post(f"/api/projects/{pid}/render")

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["project_id"] == pid
        assert body["type"] == "final_render"
        assert body["status"] == "queued"
        assert body["progress"] == 0.0
        assert body["error"] is None

    async def test_locked_animation_stage_is_4xx(self, api_env: ApiEnv) -> None:
        pid = await _locked_project(api_env)

        response = await api_env.client.post(f"/api/projects/{pid}/render")

        assert 400 <= response.status_code < 500
        assert_detail(response)

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post("/api/projects/does-not-exist/render")

        assert response.status_code == 404


class TestGetJob:
    async def test_can_query_queued_job(self, api_env: ApiEnv) -> None:
        pid = await _animation_project(api_env)
        created = await api_env.client.post(f"/api/projects/{pid}/render")
        job_id = created.json()["id"]

        response = await api_env.client.get(f"/api/projects/{pid}/jobs/{job_id}")

        assert response.status_code == 200
        assert response.json()["status"] == "queued"

    async def test_unknown_job_is_404(self, api_env: ApiEnv) -> None:
        pid = await _animation_project(api_env)

        response = await api_env.client.get(f"/api/projects/{pid}/jobs/does-not-exist")

        assert response.status_code == 404

    async def test_job_from_another_project_is_404(self, api_env: ApiEnv) -> None:
        pid_a = await _animation_project(api_env)
        pid_b = await _animation_project(api_env)
        created = await api_env.client.post(f"/api/projects/{pid_a}/render")
        job_id = created.json()["id"]

        response = await api_env.client.get(f"/api/projects/{pid_b}/jobs/{job_id}")

        assert response.status_code == 404


class TestGetLatestJob:
    async def test_no_job_yet_returns_null(self, api_env: ApiEnv) -> None:
        pid = await _animation_project(api_env)

        response = await api_env.client.get(
            f"/api/projects/{pid}/jobs/latest", params={"type": "final_render"}
        )

        assert response.status_code == 200
        assert response.json() is None

    async def test_returns_the_most_recently_created_job(self, api_env: ApiEnv) -> None:
        pid = await _animation_project(api_env)
        first = await api_env.client.post(f"/api/projects/{pid}/render")
        # `create_render_job_endpoint` doesn't check for an existing queued
        # job (TD-35), so a second POST is enough to get a distinct, newer row.
        second = await api_env.client.post(f"/api/projects/{pid}/render")

        response = await api_env.client.get(
            f"/api/projects/{pid}/jobs/latest", params={"type": "final_render"}
        )

        assert response.status_code == 200
        assert response.json()["id"] == second.json()["id"]
        assert response.json()["id"] != first.json()["id"]

    async def test_scoped_to_project(self, api_env: ApiEnv) -> None:
        pid_a = await _animation_project(api_env)
        pid_b = await _animation_project(api_env)
        await api_env.client.post(f"/api/projects/{pid_a}/render")

        response = await api_env.client.get(
            f"/api/projects/{pid_b}/jobs/latest", params={"type": "final_render"}
        )

        assert response.status_code == 200
        assert response.json() is None

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get(
            "/api/projects/does-not-exist/jobs/latest", params={"type": "final_render"}
        )

        assert response.status_code == 404


class TestDownloadFinalVideo:
    async def test_downloads_rendered_video(self, api_env: ApiEnv) -> None:
        pid = await _animation_project(api_env)
        output_dir = api_env.workdir(pid) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "final.mp4").write_bytes(b"fake-mp4-bytes")

        response = await api_env.client.get(f"/api/projects/{pid}/output/final.mp4")

        assert response.status_code == 200
        assert response.headers["content-type"] == "video/mp4"
        assert response.content == b"fake-mp4-bytes"

    async def test_missing_output_is_404(self, api_env: ApiEnv) -> None:
        pid = await _animation_project(api_env)

        response = await api_env.client.get(f"/api/projects/{pid}/output/final.mp4")

        assert response.status_code == 404
        assert_detail(response)

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/projects/does-not-exist/output/final.mp4")

        assert response.status_code == 404
