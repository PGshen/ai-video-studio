"""`/api/projects` 及定稿/重新打开接口（任务简报 T7）。"""

from __future__ import annotations

from studio.db.repo.snapshots import list_snapshots
from studio.db.repo.stages import list_stages

from .conftest import ApiEnv, assert_detail


class TestCreateProject:
    async def test_creates_workspace_stages_and_init_snapshot(self, api_env: ApiEnv) -> None:
        body = await api_env.create_project(title="我的视频")

        assert body["title"] == "我的视频"
        assert body["current_stage"] == "topic"
        project_id = body["id"]

        style = api_env.workdir(project_id) / "style" / "STYLE.md"
        assert style.is_file()

        stages = {s.stage: s.status for s in list_stages(api_env.app.state.engine, project_id)}
        assert stages == {"topic": "active", "narrative": "locked", "animation": "locked"}

        snapshots = list_snapshots(api_env.app.state.engine, project_id)
        assert len(snapshots) == 1
        assert snapshots[0].reason == "init"
        assert "style/STYLE.md" in snapshots[0].manifest

    async def test_accepts_settings(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects", json={"title": "带设置", "settings": {"aspect_ratio": "16:9"}}
        )
        assert response.status_code == 201
        assert response.json()["settings"] == {"aspect_ratio": "16:9"}


class TestListAndGetProject:
    async def test_list_returns_created_projects(self, api_env: ApiEnv) -> None:
        a = await api_env.create_project(title="A")
        b = await api_env.create_project(title="B")

        response = await api_env.client.get("/api/projects")

        assert response.status_code == 200
        ids = [p["id"] for p in response.json()]
        assert {a["id"], b["id"]} <= set(ids)

    async def test_get_includes_stage_statuses(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()

        response = await api_env.client.get(f"/api/projects/{project['id']}")

        assert response.status_code == 200
        body = response.json()
        stages = {s["stage"]: s["status"] for s in body["stages"]}
        assert stages == {"topic": "active", "narrative": "locked", "animation": "locked"}

    async def test_get_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/projects/does-not-exist")
        assert response.status_code == 404
        assert_detail(response)


class TestFinalizeAndReopen:
    async def test_finalize_unlocks_downstream_stage(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        pid = project["id"]
        (api_env.workdir(pid) / "topic").mkdir(parents=True, exist_ok=True)
        (api_env.workdir(pid) / "topic" / "brief.md").write_text("定稿简报", encoding="utf-8")

        response = await api_env.client.post(f"/api/projects/{pid}/stages/topic/finalize")

        assert response.status_code == 200
        assert response.json()["status"] == "finalized"
        narrative = next(
            s for s in list_stages(api_env.app.state.engine, pid) if s.stage == "narrative"
        )
        assert narrative.status == "active"

    async def test_reopen_finalized_stage(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        pid = project["id"]
        await api_env.client.post(f"/api/projects/{pid}/stages/topic/finalize")

        response = await api_env.client.post(f"/api/projects/{pid}/stages/topic/reopen")

        assert response.status_code == 200
        assert response.json()["status"] == "active"

    async def test_reopen_not_finalized_stage_is_conflict(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()

        response = await api_env.client.post(f"/api/projects/{project['id']}/stages/topic/reopen")

        assert response.status_code == 409
        assert_detail(response)

    async def test_unknown_stage_name_is_404(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()

        response = await api_env.client.post(
            f"/api/projects/{project['id']}/stages/no-such-stage/finalize"
        )

        assert response.status_code == 404
        assert_detail(response)

    async def test_finalize_while_project_busy_is_409(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        pid = project["id"]
        turn_id = await api_env.make_busy(pid)

        response = await api_env.client.post(f"/api/projects/{pid}/stages/topic/finalize")

        assert response.status_code == 409
        await api_env.release_busy(turn_id)

    async def test_finalize_on_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post("/api/projects/does-not-exist/stages/topic/finalize")
        assert response.status_code == 404


class TestCreateProjectFailureCleanup:
    async def test_failure_after_files_leaves_no_visible_project(
        self, api_env: ApiEnv, monkeypatch
    ) -> None:
        from studio.api import projects as projects_module

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("模拟阶段行创建失败")

        monkeypatch.setattr(projects_module, "create_stage", boom)

        response = await api_env.client.post("/api/projects", json={"title": "会失败"})

        assert response.status_code == 500
        assert_detail(response)
        # every project row that might have been inserted before the failure is gone
        listing = await api_env.client.get("/api/projects")
        assert listing.json() == []
