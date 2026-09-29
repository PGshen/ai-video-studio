"""`GET /api/projects/{id}/topic/check`（计划 M4 T6）。"""

from __future__ import annotations

from httpx import Response

from brief_builder import make_brief as _brief
from studio.workspace import files

from .conftest import ApiEnv


async def test_unknown_project_is_404(api_env: ApiEnv) -> None:
    response = await api_env.client.get("/api/projects/nope/topic/check")
    assert response.status_code == 404


async def test_missing_brief_reports_errors_not_404(api_env: ApiEnv) -> None:
    project = await api_env.create_project()
    response = await api_env.client.get(f"/api/projects/{project['id']}/topic/check")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert any("brief.md" in e for e in body["errors"])
    assert body["warnings"] == []


async def test_reflects_current_workspace_content(api_env: ApiEnv) -> None:
    project = await api_env.create_project()
    workdir = api_env.workdir(project["id"])
    files.write_text_unscoped(workdir, "topic/brief.md", _brief(风险点="没有。"))
    body = (await api_env.client.get(f"/api/projects/{project['id']}/topic/check")).json()
    assert body["ok"] is True and body["errors"] == []
    assert any("风险点" in w for w in body["warnings"])

    files.write_text_unscoped(workdir, "topic/brief.md", "## 核心问题\n\nx\n")
    body = (await api_env.client.get(f"/api/projects/{project['id']}/topic/check")).json()
    assert body["ok"] is False


class TestFinalizeIsBlockedByBriefErrors:
    @staticmethod
    async def _finalize(api_env: ApiEnv, pid: str, stage: str = "topic") -> Response:
        return await api_env.client.post(f"/api/projects/{pid}/stages/{stage}/finalize")

    async def test_missing_brief_blocks_finalize_and_leaves_stage_active(
        self, api_env: ApiEnv
    ) -> None:
        project = await api_env.create_project()
        response = await self._finalize(api_env, project["id"])
        assert response.status_code == 409
        assert "brief.md" in response.json()["detail"]
        detail = (await api_env.client.get(f"/api/projects/{project['id']}")).json()
        statuses = {s["stage"]: s["status"] for s in detail["stages"]}
        assert statuses["topic"] == "active" and statuses["narrative"] == "locked"

    async def test_incomplete_brief_lists_the_errors(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        files.write_text_unscoped(
            api_env.workdir(project["id"]), "topic/brief.md", "## 核心问题\n\n只有一章\n"
        )
        response = await self._finalize(api_env, project["id"])
        assert response.status_code == 409
        assert response.json()["detail"].count("缺少章节") == 6

    async def test_warnings_do_not_block_and_finalize_unlocks_narrative(
        self, api_env: ApiEnv
    ) -> None:
        project = await api_env.create_project()
        files.write_text_unscoped(
            api_env.workdir(project["id"]), "topic/brief.md", _brief(风险点="没有。")
        )
        response = await self._finalize(api_env, project["id"])
        assert response.status_code == 200, response.text
        detail = (await api_env.client.get(f"/api/projects/{project['id']}")).json()
        assert {s["stage"]: s["status"] for s in detail["stages"]}["narrative"] == "active"

    async def test_other_stages_are_not_blocked(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        files.write_text_unscoped(api_env.workdir(project["id"]), "topic/brief.md", _brief())
        assert (await self._finalize(api_env, project["id"])).status_code == 200
        # narrative has no blockers (confirmed by the user, not enforced; M3)
        assert (await self._finalize(api_env, project["id"], "narrative")).status_code == 200
