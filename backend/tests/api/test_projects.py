"""`/api/projects` 及定稿/重新打开接口（任务简报 T7）。"""

from __future__ import annotations

from uuid import UUID

import pytest

from brief_builder import make_brief
from studio.db.repo.ideas import IdeaStateError
from studio.db.repo.snapshots import list_snapshots
from studio.db.repo.stages import list_stages
from studio.workspace import files

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

    async def test_get_busy_is_false_when_idle(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()

        response = await api_env.client.get(f"/api/projects/{project['id']}")

        assert response.status_code == 200
        assert response.json()["busy"] is False

    async def test_get_busy_is_true_while_a_turn_is_running(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        turn_id = await api_env.make_busy(project["id"])
        try:
            response = await api_env.client.get(f"/api/projects/{project['id']}")
            assert response.status_code == 200
            assert response.json()["busy"] is True
        finally:
            await api_env.release_busy(turn_id)


class TestFinalizeAndReopen:
    async def test_finalize_unlocks_downstream_stage(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        pid = project["id"]
        files.write_text_unscoped(api_env.workdir(pid), "topic/brief.md", make_brief())

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
        files.write_text_unscoped(api_env.workdir(pid), "topic/brief.md", make_brief())
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

        fixed_id = UUID("11111111-1111-1111-1111-111111111111")
        monkeypatch.setattr(projects_module, "uuid4", lambda: fixed_id)

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("模拟阶段行创建失败")

        monkeypatch.setattr(projects_module, "create_stage", boom)

        response = await api_env.client.post("/api/projects", json={"title": "会失败"})

        assert response.status_code == 500
        assert_detail(response)
        # every project row that might have been inserted before the failure is gone
        listing = await api_env.client.get("/api/projects")
        assert listing.json() == []
        # the `init` snapshot created by `_init_workspace` before the DB rows
        # is not left orphaned either (review finding: was previously leaked).
        assert list_snapshots(api_env.app.state.engine, fixed_id.hex) == []


class TestCreateProjectFromIdea:
    async def _idea(self, api_env: ApiEnv, **extra: object) -> dict:
        response = await api_env.client.post(
            "/api/ideas",
            json={
                "title": "排序为什么这么快",
                "pitch": "十亿条记录一秒排完",
                "counterintuitive": "大家以为排序慢，其实分治让它很快",
                "tags": ["算法", "排序"],
                "scores": {"counterintuitive": 5, "visual": 4},
                **extra,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def test_creates_project_linked_to_idea_and_marks_it_picked(
        self, api_env: ApiEnv
    ) -> None:
        idea = await self._idea(api_env)
        response = await api_env.client.post(
            "/api/projects", json={"title": "排序视频", "idea_id": idea["id"]}
        )
        assert response.status_code == 201, response.text
        project = response.json()
        assert project["idea_id"] == idea["id"]

        card = (await api_env.client.get(f"/api/ideas/{idea['id']}")).json()
        assert card["status"] == "picked"
        assert card["project_id"] == project["id"]

    async def test_idea_card_is_seeded_into_workspace_and_init_snapshot(
        self, api_env: ApiEnv
    ) -> None:
        idea = await self._idea(api_env)
        project = (
            await api_env.client.post(
                "/api/projects", json={"title": "排序视频", "idea_id": idea["id"]}
            )
        ).json()

        path = api_env.workdir(project["id"]) / "topic" / "notes" / "idea-card.md"
        text = path.read_text(encoding="utf-8")
        assert "排序为什么这么快" in text
        assert "十亿条记录一秒排完" in text
        assert "大家以为排序慢，其实分治让它很快" in text
        assert "算法" in text
        assert "反直觉" in text and "5" in text

        snapshots = list_snapshots(api_env.app.state.engine, project["id"])
        assert len(snapshots) == 1 and snapshots[0].reason == "init"
        assert "topic/notes/idea-card.md" in snapshots[0].manifest
        assert "style/STYLE.md" in snapshots[0].manifest

    async def test_card_without_optional_fields_renders(self, api_env: ApiEnv) -> None:
        idea = (await api_env.client.post("/api/ideas", json={"title": "只有标题"})).json()
        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "idea_id": idea["id"]}
        )
        assert response.status_code == 201
        text = (
            api_env.workdir(response.json()["id"]) / "topic" / "notes" / "idea-card.md"
        ).read_text(encoding="utf-8")
        assert "只有标题" in text

    async def test_unknown_idea_is_404_and_leaves_nothing(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "idea_id": "nope"}
        )
        assert response.status_code == 404
        assert (await api_env.client.get("/api/projects")).json() == []
        assert not (api_env.data_dir / "projects").exists() or not list(
            (api_env.data_dir / "projects").iterdir()
        )

    async def test_picked_idea_cannot_be_used_twice(self, api_env: ApiEnv) -> None:
        idea = await self._idea(api_env)
        first = await api_env.client.post(
            "/api/projects", json={"title": "P1", "idea_id": idea["id"]}
        )
        assert first.status_code == 201
        second = await api_env.client.post(
            "/api/projects", json={"title": "P2", "idea_id": idea["id"]}
        )
        assert second.status_code == 409
        assert len((await api_env.client.get("/api/projects")).json()) == 1

    async def test_archived_idea_is_409(self, api_env: ApiEnv) -> None:
        idea = await self._idea(api_env)
        await api_env.client.patch(f"/api/ideas/{idea['id']}", json={"status": "archived"})
        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "idea_id": idea["id"]}
        )
        assert response.status_code == 409

    async def test_losing_the_race_cleans_up_the_project(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        idea = await self._idea(api_env)

        def lose(engine: object, idea_id: str, project_id: str) -> None:
            raise IdeaStateError("已被别的项目选走")

        monkeypatch.setattr("studio.api.projects.mark_picked", lose)
        response = await api_env.client.post(
            "/api/projects", json={"title": "P", "idea_id": idea["id"]}
        )
        assert response.status_code == 409
        assert (await api_env.client.get("/api/projects")).json() == []
        card = (await api_env.client.get(f"/api/ideas/{idea['id']}")).json()
        assert card["status"] == "idea"

    async def test_project_without_idea_still_works(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        assert project["idea_id"] is None
        assert not (api_env.workdir(project["id"]) / "topic").exists()
