"""`GET /api/projects/{id}/topic/check`（计划 M4 T6）。"""

from __future__ import annotations

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
