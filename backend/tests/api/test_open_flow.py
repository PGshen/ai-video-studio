"""完全自由项目的完成流程与渲染类接口（open-mode 设计 §6）。"""

from __future__ import annotations

from typing import Any

from studio.db.repo.projects import get_project

from .conftest import ApiEnv, assert_detail


async def _create_open(api_env: ApiEnv) -> dict[str, Any]:
    response = await api_env.client.post("/api/projects", json={"title": "开放", "mode": "open"})
    assert response.status_code == 201, response.text
    return response.json()


def _completed_at(api_env: ApiEnv, project_id: str) -> object:
    project = get_project(api_env.app.state.engine, project_id)
    assert project is not None
    return project.completed_at


async def test_open_stage_is_registered_and_the_card_is_available(api_env: ApiEnv) -> None:
    body = (await api_env.client.get("/api/video-kinds")).json()

    (kind,) = [k for k in body["kinds"] if k["mode"] == "open"]
    assert kind["available"] is True


async def test_finalize_marks_the_project_complete_and_reopen_clears_it(api_env: ApiEnv) -> None:
    pid = (await _create_open(api_env))["id"]
    (api_env.workdir(pid) / "out.mp4").write_bytes(b"video")

    first = await api_env.client.post(f"/api/projects/{pid}/stages/open/finalize")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "finalized"
    assert _completed_at(api_env, pid) is not None
    assert (await api_env.client.get(f"/api/projects/{pid}")).json()["status"] == "completed"

    reopened = await api_env.client.post(f"/api/projects/{pid}/stages/open/reopen")
    assert reopened.status_code == 200, reopened.text
    assert _completed_at(api_env, pid) is None

    again = await api_env.client.post(f"/api/projects/{pid}/stages/open/finalize")
    assert again.status_code == 200, again.text
    assert _completed_at(api_env, pid) is not None


async def test_finalizing_a_staged_stage_does_not_complete_the_project(api_env: ApiEnv) -> None:
    pid = (await api_env.create_project())["id"]
    workdir = api_env.workdir(pid)
    (workdir / "topic").mkdir(exist_ok=True)

    await api_env.client.post(f"/api/projects/{pid}/stages/topic/finalize")

    assert _completed_at(api_env, pid) is None


async def test_render_endpoints_refuse_open_projects(api_env: ApiEnv) -> None:
    pid = (await _create_open(api_env))["id"]

    for url in (f"/api/projects/{pid}/render", f"/api/projects/{pid}/animation/finalize-render"):
        response = await api_env.client.post(url)
        assert response.status_code == 409, url
        assert assert_detail(response) == "完全自由项目没有成片渲染"


async def test_scene_checks_are_not_run_for_open_projects(api_env: ApiEnv) -> None:
    pid = (await _create_open(api_env))["id"]

    response = await api_env.client.get(f"/api/projects/{pid}/animation/scene-checks")

    assert response.status_code == 200, response.text
