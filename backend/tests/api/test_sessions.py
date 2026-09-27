"""`/api/projects/{id}/stages/{stage}/sessions`、`/api/sessions/{id}*`（任务简报 T8）。"""

from __future__ import annotations

from studio.agent import register_fake
from studio.agent.fake import FakeRuntime, sleep
from studio.agent.runtime import UserInput
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.turns import (
    create_turn_if_session_idle,
    finish_turn,
    interrupt_turn,
    mark_turn_running,
)

from .conftest import ApiEnv, assert_detail


async def _project(api_env: ApiEnv) -> str:
    body = await api_env.create_project()
    return body["id"]


def _fake_profile_id(api_env: ApiEnv) -> str:
    profile = get_model_profile(api_env.app.state.engine, "fake")
    assert profile is not None
    return profile.id


async def _make_busy_session(
    api_env: ApiEnv, project_id: str, stage: str = "topic"
) -> tuple[str, str]:
    """新建一个会话，让它跑一个永不结束的 turn；返回 (session_id, turn_id)。

    调用方用完必须调用 `_release_busy_session` 清理。
    """
    session = create_session(
        api_env.app.state.engine,
        project_id=project_id,
        stage=stage,
        model_profile_id=_fake_profile_id(api_env),
        runtime="fake",
    )
    api_env.app.state.runtime_factory.register("fake", lambda: FakeRuntime([sleep(30)]))
    turn_id = await api_env.app.state.turn_runner.start_turn(session.id, UserInput(text="占位"))
    return session.id, turn_id


async def _release_busy_session(api_env: ApiEnv, turn_id: str) -> None:
    api_env.app.state.turn_runner.cancel(turn_id)
    await api_env.app.state.turn_runner.wait(turn_id)
    register_fake(api_env.app.state.runtime_factory)


class TestCreateSession:
    async def test_creates_active_session_and_deactivates_previous(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        profile_id = _fake_profile_id(api_env)

        first = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions", json={"model_profile_id": profile_id}
        )
        assert first.status_code == 201, first.text
        assert first.json()["is_active"] is True
        assert first.json()["runtime"] == "fake"
        assert first.json()["status"] == "idle"

        second = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions", json={"model_profile_id": profile_id}
        )
        assert second.status_code == 201

        listing = await api_env.client.get(f"/api/projects/{pid}/stages/topic/sessions")
        assert listing.status_code == 200
        by_id = {s["id"]: s["is_active"] for s in listing.json()}
        assert by_id[first.json()["id"]] is False
        assert by_id[second.json()["id"]] is True

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects/does-not-exist/stages/topic/sessions",
            json={"model_profile_id": "does-not-matter"},
        )
        assert response.status_code == 404

    async def test_unknown_stage_is_404(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        response = await api_env.client.post(
            f"/api/projects/{pid}/stages/no-such-stage/sessions",
            json={"model_profile_id": _fake_profile_id(api_env)},
        )
        assert response.status_code == 404

    async def test_unknown_model_profile_is_404(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        response = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions",
            json={"model_profile_id": "does-not-exist"},
        )
        assert response.status_code == 404
        assert_detail(response)

    async def test_unregistered_runtime_is_400(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        claude_profile = get_model_profile(api_env.app.state.engine, "claude-sonnet")
        assert claude_profile is not None

        response = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions",
            json={"model_profile_id": claude_profile.id},
        )

        assert response.status_code == 400
        assert_detail(response)


class TestListSessions:
    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/projects/does-not-exist/stages/topic/sessions")
        assert response.status_code == 404

    async def test_lists_only_matching_project_and_stage(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        profile_id = _fake_profile_id(api_env)
        await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions", json={"model_profile_id": profile_id}
        )
        await api_env.client.post(
            f"/api/projects/{pid}/stages/narrative/sessions", json={"model_profile_id": profile_id}
        )

        response = await api_env.client.get(f"/api/projects/{pid}/stages/topic/sessions")

        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["stage"] == "topic"


class TestGetSession:
    async def test_unknown_session_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/sessions/does-not-exist")
        assert response.status_code == 404

    async def test_includes_turns(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        created = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions",
            json={"model_profile_id": _fake_profile_id(api_env)},
        )
        session_id = created.json()["id"]

        sent = await api_env.client.post(
            f"/api/sessions/{session_id}/messages", json={"text": "你好"}
        )
        assert sent.status_code == 202, sent.text
        turn_id = sent.json()["turn_id"]
        await api_env.app.state.turn_runner.wait(turn_id)

        response = await api_env.client.get(f"/api/sessions/{session_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == session_id
        assert len(body["turns"]) == 1
        turn = body["turns"][0]
        assert turn["id"] == turn_id
        assert turn["user_message"] == "你好"
        assert turn["status"] == "done"
        assert turn["end_snapshot_id"] is not None


class TestSendMessage:
    async def test_returns_202_with_turn_id(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        created = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions",
            json={"model_profile_id": _fake_profile_id(api_env)},
        )
        session_id = created.json()["id"]

        response = await api_env.client.post(
            f"/api/sessions/{session_id}/messages", json={"text": "你好"}
        )

        assert response.status_code == 202
        assert "turn_id" in response.json()
        await api_env.app.state.turn_runner.wait(response.json()["turn_id"])

    async def test_unknown_session_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/sessions/does-not-exist/messages", json={"text": "你好"}
        )
        assert response.status_code == 404

    async def test_busy_session_is_409(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        session_id, turn_id = await _make_busy_session(api_env, pid)

        response = await api_env.client.post(
            f"/api/sessions/{session_id}/messages", json={"text": "再来一条"}
        )

        assert response.status_code == 409
        assert_detail(response)
        await _release_busy_session(api_env, turn_id)


class TestCancelSession:
    async def test_unknown_session_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post("/api/sessions/does-not-exist/cancel")
        assert response.status_code == 404

    async def test_no_running_turn_is_409(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        created = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions",
            json={"model_profile_id": _fake_profile_id(api_env)},
        )
        session_id = created.json()["id"]

        response = await api_env.client.post(f"/api/sessions/{session_id}/cancel")

        assert response.status_code == 409
        assert_detail(response)

    async def test_cancels_running_turn(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        session_id, turn_id = await _make_busy_session(api_env, pid)

        response = await api_env.client.post(f"/api/sessions/{session_id}/cancel")

        assert response.status_code == 202
        assert response.json()["turn_id"] == turn_id
        await api_env.app.state.turn_runner.wait(turn_id)
        register_fake(api_env.app.state.runtime_factory)

        detail = await api_env.client.get(f"/api/sessions/{session_id}")
        assert detail.json()["turns"][0]["status"] == "cancelled"


class TestContinueSession:
    async def test_unknown_session_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post("/api/sessions/does-not-exist/continue")
        assert response.status_code == 404

    async def test_no_turn_is_409(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        created = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions",
            json={"model_profile_id": _fake_profile_id(api_env)},
        )
        session_id = created.json()["id"]

        response = await api_env.client.post(f"/api/sessions/{session_id}/continue")

        assert response.status_code == 409
        assert_detail(response)

    async def test_done_turn_is_409(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        created = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions",
            json={"model_profile_id": _fake_profile_id(api_env)},
        )
        session_id = created.json()["id"]
        sent = await api_env.client.post(
            f"/api/sessions/{session_id}/messages", json={"text": "你好"}
        )
        await api_env.app.state.turn_runner.wait(sent.json()["turn_id"])

        response = await api_env.client.post(f"/api/sessions/{session_id}/continue")

        assert response.status_code == 409

    async def test_interrupted_turn_can_be_continued_with_fixed_text(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        engine = api_env.app.state.engine
        session = create_session(
            engine,
            project_id=pid,
            stage="topic",
            model_profile_id=_fake_profile_id(api_env),
            runtime="fake",
        )
        stuck = create_turn_if_session_idle(engine, session.id, "第一条")
        assert stuck is not None
        mark_turn_running(engine, stuck.id, start_snapshot_id=None)
        interrupt_turn(engine, stuck.id, end_snapshot_id=None)

        response = await api_env.client.post(f"/api/sessions/{session.id}/continue")

        assert response.status_code == 202, response.text
        new_turn_id = response.json()["turn_id"]
        assert new_turn_id != stuck.id
        await api_env.app.state.turn_runner.wait(new_turn_id)

        detail = await api_env.client.get(f"/api/sessions/{session.id}")
        turns = {t["id"]: t for t in detail.json()["turns"]}
        assert turns[new_turn_id]["user_message"] == "继续"
        assert turns[new_turn_id]["status"] == "done"

    async def test_budget_exceeded_turn_can_be_continued(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        engine = api_env.app.state.engine
        session = create_session(
            engine,
            project_id=pid,
            stage="topic",
            model_profile_id=_fake_profile_id(api_env),
            runtime="fake",
        )
        stuck = create_turn_if_session_idle(engine, session.id, "第一条")
        assert stuck is not None
        mark_turn_running(engine, stuck.id, start_snapshot_id=None)
        finish_turn(
            engine,
            stuck.id,
            status="budget_exceeded",
            end_snapshot_id=None,
            usage=None,
            cost_usd=None,
            error=None,
            resume_ref=None,
        )

        response = await api_env.client.post(f"/api/sessions/{session.id}/continue")

        assert response.status_code == 202
        await api_env.app.state.turn_runner.wait(response.json()["turn_id"])
