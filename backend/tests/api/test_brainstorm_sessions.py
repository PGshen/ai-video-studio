"""`/api/brainstorm/sessions`（计划 M4 T3）：没有项目的头脑风暴会话。"""

from __future__ import annotations

import asyncio

from studio.db.engine import session_scope
from studio.db.models import ModelProfile
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.turns import list_events

from .conftest import ApiEnv, assert_detail


def _fake_profile_id(api_env: ApiEnv) -> str:
    profile = get_model_profile(api_env.app.state.engine, "fake")
    assert profile is not None
    return profile.id


async def _create(api_env: ApiEnv, profile_id: str | None = None) -> dict:
    response = await api_env.client.post(
        "/api/brainstorm/sessions",
        json={"model_profile_id": profile_id or _fake_profile_id(api_env)},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _wait_turn(api_env: ApiEnv, session_id: str) -> dict:
    for _ in range(200):
        detail = (await api_env.client.get(f"/api/sessions/{session_id}")).json()
        if detail["turns"] and detail["turns"][-1]["status"] not in ("queued", "running"):
            return detail
        await asyncio.sleep(0.01)
    raise AssertionError("turn did not finish")


class TestCreateAndList:
    async def test_creates_session_without_project(self, api_env: ApiEnv) -> None:
        body = await _create(api_env)
        assert body["project_id"] is None
        assert body["stage"] == "brainstorm"
        assert body["runtime"] == "fake"
        assert body["is_active"] is True
        assert body["status"] == "idle"

    async def test_new_session_deactivates_previous_brainstorm_session(
        self, api_env: ApiEnv
    ) -> None:
        first = await _create(api_env)
        second = await _create(api_env)
        listing = (await api_env.client.get("/api/brainstorm/sessions")).json()
        assert {s["id"]: s["is_active"] for s in listing} == {
            first["id"]: False,
            second["id"]: True,
        }

    async def test_listing_only_contains_brainstorm_sessions(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        await api_env.client.post(
            f"/api/projects/{project['id']}/stages/topic/sessions",
            json={"model_profile_id": _fake_profile_id(api_env)},
        )
        brainstorm = await _create(api_env)
        listing = (await api_env.client.get("/api/brainstorm/sessions")).json()
        assert [s["id"] for s in listing] == [brainstorm["id"]]

    async def test_project_sessions_stay_active_when_brainstorm_session_is_created(
        self, api_env: ApiEnv
    ) -> None:
        project = await api_env.create_project()
        topic = (
            await api_env.client.post(
                f"/api/projects/{project['id']}/stages/topic/sessions",
                json={"model_profile_id": _fake_profile_id(api_env)},
            )
        ).json()
        await _create(api_env)
        listing = (
            await api_env.client.get(f"/api/projects/{project['id']}/stages/topic/sessions")
        ).json()
        assert [(s["id"], s["is_active"]) for s in listing] == [(topic["id"], True)]

    async def test_unknown_profile_is_400(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/brainstorm/sessions", json={"model_profile_id": "nope"}
        )
        assert response.status_code == 400
        assert "模型配置" in assert_detail(response)

    async def test_runtime_not_enabled_is_400(self, api_env: ApiEnv) -> None:
        with session_scope(api_env.app.state.engine) as db:
            profile = ModelProfile(name="ghost", provider="x", model="x", runtime="ghost")
            db.add(profile)
            db.flush()
            profile_id = profile.id
        response = await api_env.client.post(
            "/api/brainstorm/sessions", json={"model_profile_id": profile_id}
        )
        assert response.status_code == 400
        assert "运行时" in assert_detail(response)

    async def test_project_stage_endpoint_rejects_brainstorm_stage(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        response = await api_env.client.post(
            f"/api/projects/{project['id']}/stages/brainstorm/sessions",
            json={"model_profile_id": _fake_profile_id(api_env)},
        )
        assert response.status_code == 404


class TestRunATurn:
    async def test_message_runs_a_turn_and_streams_persisted_events(self, api_env: ApiEnv) -> None:
        session = await _create(api_env)
        response = await api_env.client.post(
            f"/api/sessions/{session['id']}/messages", json={"text": "聊聊排序"}
        )
        assert response.status_code == 202, response.text

        detail = await _wait_turn(api_env, session["id"])
        turn = detail["turns"][-1]
        assert turn["status"] == "done"
        assert turn["start_snapshot_id"] is None and turn["end_snapshot_id"] is None
        assert detail["status"] == "idle"

        # Fake 默认脚本在没有可写目录时只回显；事件落库，且没有快照事件。
        rows = list_events(api_env.app.state.engine, session["id"])
        assert [r.type for r in rows] == ["text"]
        assert rows[0].payload["text"] == "收到：聊聊排序"
