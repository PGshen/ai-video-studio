"""`/api/projects/{id}/stages/{stage}/sessions`、`/api/sessions/{id}*`（任务简报 T8）。"""

from __future__ import annotations

import pytest
from httpx import Response

from studio.agent import register_fake
from studio.agent.fake import FakeRuntime, sleep
from studio.agent.runtime import UserInput
from studio.db.engine import session_scope
from studio.db.models import ModelProfile, Session
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.turns import (
    NEVER_STARTED_ERROR,
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

    async def test_unknown_model_profile_is_400(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        response = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions",
            json={"model_profile_id": "does-not-exist"},
        )
        assert response.status_code == 400
        assert_detail(response)

    async def test_real_runtimes_are_registered_at_startup(self, api_env: ApiEnv) -> None:
        factory = api_env.app.state.runtime_factory
        assert factory.has("claude") and factory.has("openai")

    async def test_unregistered_runtime_is_400(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        # `claude` is always registered since T9; use a runtime nobody registers.
        with session_scope(api_env.app.state.engine) as db:
            row = ModelProfile(name="orphan", provider="x", model="x", runtime="unregistered")
            db.add(row)
            db.flush()
            profile_id = row.id

        response = await api_env.client.post(
            f"/api/projects/{pid}/stages/topic/sessions",
            json={"model_profile_id": profile_id},
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

    async def test_other_session_of_busy_project_is_queued_not_rejected(
        self, api_env: ApiEnv
    ) -> None:
        """控制者裁定 3：项目忙不拒绝消息——`TurnRunner` 内部排队，202。"""
        pid = await _project(api_env)
        busy_session_id, busy_turn_id = await _make_busy_session(api_env, pid, stage="topic")
        other_created = await api_env.client.post(
            f"/api/projects/{pid}/stages/narrative/sessions",
            json={"model_profile_id": _fake_profile_id(api_env)},
        )
        other_session_id = other_created.json()["id"]

        response = await api_env.client.post(
            f"/api/sessions/{other_session_id}/messages", json={"text": "另一个阶段的消息"}
        )

        assert response.status_code == 202, response.text
        other_turn_id = response.json()["turn_id"]
        # 项目还在忙，这个 turn 只能排队，不会立刻运行。
        detail = await api_env.client.get(f"/api/sessions/{other_session_id}")
        assert detail.json()["turns"][0]["status"] == "queued"

        # 先复位 `fake` 注册，再释放忙会话——这样不管 `other_turn_id` 什么时候
        # 真正开始执行（`TurnRunner._schedule` 何时把它排上，不受本测试控制），
        # 拿到的都是默认的（秒结束的）fake 脚本，不会被 `sleep(30)` 卡住。
        register_fake(api_env.app.state.runtime_factory)
        api_env.app.state.turn_runner.cancel(busy_turn_id)
        await api_env.app.state.turn_runner.wait(busy_turn_id)
        await api_env.app.state.turn_runner.wait(other_turn_id)
        detail = await api_env.client.get(f"/api/sessions/{other_session_id}")
        assert detail.json()["turns"][0]["status"] == "done"


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

    async def test_never_started_turn_is_resent_with_original_message(
        self, api_env: ApiEnv
    ) -> None:
        # TD-19: a queued turn interrupted by a restart never ran; continue re-sends
        # the user's original message instead of a bare "继续".
        pid = await _project(api_env)
        engine = api_env.app.state.engine
        session = create_session(
            engine,
            project_id=pid,
            stage="topic",
            model_profile_id=_fake_profile_id(api_env),
            runtime="fake",
        )
        queued = create_turn_if_session_idle(engine, session.id, "帮我想三个选题")
        assert queued is not None
        interrupt_turn(engine, queued.id, end_snapshot_id=None, error=NEVER_STARTED_ERROR)

        detail = await api_env.client.get(f"/api/sessions/{session.id}")
        assert detail.json()["turns"][0]["never_started"] is True

        response = await api_env.client.post(f"/api/sessions/{session.id}/continue")

        assert response.status_code == 202, response.text
        new_turn_id = response.json()["turn_id"]
        await api_env.app.state.turn_runner.wait(new_turn_id)
        detail = await api_env.client.get(f"/api/sessions/{session.id}")
        turns = {t["id"]: t for t in detail.json()["turns"]}
        assert turns[new_turn_id]["user_message"] == "帮我想三个选题"
        assert turns[new_turn_id]["never_started"] is False

    async def test_started_turn_is_not_flagged_never_started(self, api_env: ApiEnv) -> None:
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

        detail = await api_env.client.get(f"/api/sessions/{session.id}")

        assert detail.json()["turns"][0]["never_started"] is False

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


def _add_profile(api_env: ApiEnv, name: str, **fields: object) -> str:
    """同 runtime（fake）、同 provider（fake）的另一个配置——换模型的合法目标。"""
    values: dict[str, object] = {"provider": "fake", "model": f"{name}-model", "runtime": "fake"}
    with session_scope(api_env.app.state.engine) as db:
        row = ModelProfile(name=name, **{**values, **fields})
        db.add(row)
        db.flush()
        return row.id


class TestSwitchModel:
    async def _session(self, api_env: ApiEnv) -> str:
        pid = await _project(api_env)
        return create_session(
            api_env.app.state.engine,
            project_id=pid,
            stage="topic",
            model_profile_id=_fake_profile_id(api_env),
            runtime="fake",
        ).id

    async def _patch(self, api_env: ApiEnv, session_id: str, profile_id: str) -> Response:
        return await api_env.client.patch(
            f"/api/sessions/{session_id}", json={"model_profile_id": profile_id}
        )

    async def test_switches_to_another_profile_of_the_same_runtime_and_provider(
        self, api_env: ApiEnv
    ) -> None:
        session_id = await self._session(api_env)
        other = _add_profile(api_env, "fake-b")

        response = await self._patch(api_env, session_id, other)

        assert response.status_code == 200, response.text
        assert response.json()["model_profile_id"] == other
        fetched = await api_env.client.get(f"/api/sessions/{session_id}")
        assert fetched.json()["model_profile_id"] == other

    async def test_keeps_sdk_ref_runtime_and_active_flag(self, api_env: ApiEnv) -> None:
        session_id = await self._session(api_env)
        engine = api_env.app.state.engine
        with session_scope(engine) as db:
            row = db.get(Session, session_id)
            assert row is not None
            row.sdk_ref = "sdk-abc"
        other = _add_profile(api_env, "fake-b")

        body = (await self._patch(api_env, session_id, other)).json()

        assert body["sdk_ref"] == "sdk-abc"
        assert body["runtime"] == "fake"
        assert body["is_active"] is True

    async def test_switching_to_the_current_profile_is_a_no_op_200(self, api_env: ApiEnv) -> None:
        session_id = await self._session(api_env)

        response = await self._patch(api_env, session_id, _fake_profile_id(api_env))

        assert response.status_code == 200
        assert response.json()["model_profile_id"] == _fake_profile_id(api_env)

    async def test_a_switched_session_runs_its_next_turn_with_the_new_profile(
        self, api_env: ApiEnv
    ) -> None:
        session_id = await self._session(api_env)
        other = _add_profile(api_env, "fake-b")
        await self._patch(api_env, session_id, other)

        sent = await api_env.client.post(
            f"/api/sessions/{session_id}/messages", json={"text": "你好"}
        )
        await api_env.app.state.turn_runner.wait(sent.json()["turn_id"])

        detail = (await api_env.client.get(f"/api/sessions/{session_id}")).json()
        assert detail["turns"][-1]["usage"]["profile_name"] == "fake-b"

    async def test_unknown_session_is_404(self, api_env: ApiEnv) -> None:
        response = await self._patch(api_env, "nope", _fake_profile_id(api_env))

        assert response.status_code == 404

    async def test_unknown_profile_is_400(self, api_env: ApiEnv) -> None:
        session_id = await self._session(api_env)

        response = await self._patch(api_env, session_id, "missing")

        assert response.status_code == 400
        assert "模型配置不存在" in assert_detail(response)

    async def test_different_runtime_is_400(self, api_env: ApiEnv) -> None:
        session_id = await self._session(api_env)
        login = get_model_profile(api_env.app.state.engine, "claude-login")
        assert login is not None

        response = await self._patch(api_env, session_id, login.id)

        assert response.status_code == 400
        assert "运行时" in assert_detail(response)

    async def test_different_provider_is_400(self, api_env: ApiEnv) -> None:
        session_id = await self._session(api_env)
        other = _add_profile(api_env, "fake-other-vendor", provider="other-vendor")

        response = await self._patch(api_env, session_id, other)

        assert response.status_code == 400
        assert "供应商" in assert_detail(response)

    async def _claude_session(self, api_env: ApiEnv, profile_id: str) -> str:
        pid = await _project(api_env)
        return create_session(
            api_env.app.state.engine,
            project_id=pid,
            stage="topic",
            model_profile_id=profile_id,
            runtime="claude",
        ).id

    async def test_claude_sessions_can_switch_within_the_same_auth_mode(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SMOKE_TEST_ANTHROPIC_KEY", "sk-test")
        claude = {"provider": "anthropic", "runtime": "claude"}
        login_a = _add_profile(api_env, "login-a", api_key_env=None, **claude)
        login_b = _add_profile(api_env, "login-b", api_key_env=None, **claude)
        key_a = _add_profile(api_env, "key-a", api_key_env="SMOKE_TEST_ANTHROPIC_KEY", **claude)
        key_b = _add_profile(api_env, "key-b", api_key_env="SMOKE_TEST_ANTHROPIC_KEY", **claude)

        for source, target in ((login_a, login_b), (key_a, key_b)):
            session_id = await self._claude_session(api_env, source)
            response = await self._patch(api_env, session_id, target)
            assert response.status_code == 200, response.text
            assert response.json()["model_profile_id"] == target

    async def test_claude_sessions_cannot_switch_between_login_and_api_key(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """登录 ↔ API key 互换后 SDK 会话能否续上没有验证过（要 API key 付费实测），先不允许。"""
        monkeypatch.setenv("SMOKE_TEST_ANTHROPIC_KEY", "sk-test")
        claude = {"provider": "anthropic", "runtime": "claude"}
        login = _add_profile(api_env, "login-a", api_key_env=None, **claude)
        key = _add_profile(api_env, "key-a", api_key_env="SMOKE_TEST_ANTHROPIC_KEY", **claude)

        for source, target in ((login, key), (key, login)):
            session_id = await self._claude_session(api_env, source)
            response = await self._patch(api_env, session_id, target)
            assert response.status_code == 400
            assert "认证方式" in assert_detail(response)
            fetched = await api_env.client.get(f"/api/sessions/{session_id}")
            assert fetched.json()["model_profile_id"] == source

    async def test_non_claude_runtimes_are_not_limited_by_the_auth_env(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI 路径的会话历史（SQLiteSession）与模型和 key 无关，同 provider 内可以互换。"""
        monkeypatch.setenv("SMOKE_TEST_OTHER_KEY", "sk-test")
        a = _add_profile(api_env, "oa", api_key_env="OPENAI_API_KEY", provider="openai")
        b = _add_profile(api_env, "ob", api_key_env="SMOKE_TEST_OTHER_KEY", provider="openai")
        pid = await _project(api_env)
        session_id = create_session(
            api_env.app.state.engine,
            project_id=pid,
            stage="topic",
            model_profile_id=a,
            runtime="fake",
        ).id
        # 两个配置的 runtime 都是 fake（`_add_profile` 默认），所以只受 provider 和 key 限制。

        response = await self._patch(api_env, session_id, b)

        assert response.status_code == 200, response.text

    async def test_profile_without_configured_key_is_400(self, api_env: ApiEnv) -> None:
        session_id = await self._session(api_env)
        other = _add_profile(api_env, "fake-nokey", api_key_env="SURELY_UNSET_KEY_ENV_VAR")

        response = await self._patch(api_env, session_id, other)

        assert response.status_code == 400
        assert "密钥" in assert_detail(response)
        fetched = await api_env.client.get(f"/api/sessions/{session_id}")
        assert fetched.json()["model_profile_id"] == _fake_profile_id(api_env)

    async def test_unregistered_runtime_is_400(self, api_env: ApiEnv) -> None:
        session_id = await self._session(api_env)
        other = _add_profile(api_env, "fake-b")
        api_env.app.state.runtime_factory._constructors.pop("fake")

        response = await self._patch(api_env, session_id, other)

        assert response.status_code == 400
        assert "运行时未启用" in assert_detail(response)

    async def test_running_turn_is_409_and_changes_nothing(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        session_id, turn_id = await _make_busy_session(api_env, pid)
        other = _add_profile(api_env, "fake-b")
        try:
            response = await self._patch(api_env, session_id, other)

            assert response.status_code == 409
            assert "正在运行" in assert_detail(response)
            fetched = await api_env.client.get(f"/api/sessions/{session_id}")
            assert fetched.json()["model_profile_id"] == _fake_profile_id(api_env)
        finally:
            await _release_busy_session(api_env, turn_id)

    async def test_after_the_turn_ends_the_switch_is_allowed(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        session_id, turn_id = await _make_busy_session(api_env, pid)
        other = _add_profile(api_env, "fake-b")
        await _release_busy_session(api_env, turn_id)

        response = await self._patch(api_env, session_id, other)

        assert response.status_code == 200

    async def test_brainstorm_sessions_can_switch_too(self, api_env: ApiEnv) -> None:
        created = await api_env.client.post(
            "/api/brainstorm/sessions", json={"model_profile_id": _fake_profile_id(api_env)}
        )
        assert created.status_code == 201, created.text
        other = _add_profile(api_env, "fake-b")

        response = await self._patch(api_env, created.json()["id"], other)

        assert response.status_code == 200
        assert response.json()["project_id"] is None


class TestDeleteSession:
    async def test_unknown_session_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.delete("/api/sessions/does-not-exist")
        assert response.status_code == 404

    async def test_deletes_session_with_turns_and_promotes_latest_active(
        self, api_env: ApiEnv
    ) -> None:
        pid = await _project(api_env)
        profile_id = _fake_profile_id(api_env)
        first = (
            await api_env.client.post(
                f"/api/projects/{pid}/stages/topic/sessions", json={"model_profile_id": profile_id}
            )
        ).json()
        second = (
            await api_env.client.post(
                f"/api/projects/{pid}/stages/topic/sessions", json={"model_profile_id": profile_id}
            )
        ).json()
        turn = create_turn_if_session_idle(api_env.app.state.engine, second["id"], "你好")
        assert turn is not None
        mark_turn_running(api_env.app.state.engine, turn.id, start_snapshot_id=None)
        finish_turn(
            api_env.app.state.engine,
            turn.id,
            status="done",
            end_snapshot_id=None,
            usage=None,
            cost_usd=None,
            error=None,
            resume_ref=None,
        )

        response = await api_env.client.delete(f"/api/sessions/{second['id']}")

        assert response.status_code == 204
        assert (await api_env.client.get(f"/api/sessions/{second['id']}")).status_code == 404
        remaining = (await api_env.client.get(f"/api/projects/{pid}/stages/topic/sessions")).json()
        assert [s["id"] for s in remaining] == [first["id"]]
        assert remaining[0]["is_active"] is True

    async def test_busy_session_is_409_and_kept(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        session_id, turn_id = await _make_busy_session(api_env, pid)
        try:
            response = await api_env.client.delete(f"/api/sessions/{session_id}")
            assert response.status_code == 409
            assert_detail(response)
            assert (await api_env.client.get(f"/api/sessions/{session_id}")).status_code == 200
        finally:
            await _release_busy_session(api_env, turn_id)


class TestAutoTitle:
    async def test_untitled_until_first_message_then_named_after_it(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        session = (
            await api_env.client.post(
                f"/api/projects/{pid}/stages/topic/sessions",
                json={"model_profile_id": _fake_profile_id(api_env)},
            )
        ).json()
        assert session["title"] is None

        engine = api_env.app.state.engine
        for text in ("继续", "  帮我想几个\n关于算法的选题  "):
            turn = create_turn_if_session_idle(engine, session["id"], text)
            assert turn is not None
            mark_turn_running(engine, turn.id, start_snapshot_id=None)
            finish_turn(
                engine,
                turn.id,
                status="done",
                end_snapshot_id=None,
                usage=None,
                cost_usd=None,
                error=None,
                resume_ref=None,
            )

        listed = (await api_env.client.get(f"/api/projects/{pid}/stages/topic/sessions")).json()
        assert listed[0]["title"] == "帮我想几个"
        detail = (await api_env.client.get(f"/api/sessions/{session['id']}")).json()
        assert detail["title"] == "帮我想几个"

    async def test_long_message_is_truncated(self, api_env: ApiEnv) -> None:
        from studio.db.repo.sessions import TITLE_MAX_CHARS, derive_title

        title = derive_title("长" * 100)
        assert title == "长" * TITLE_MAX_CHARS + "…"
        assert derive_title("  \n ") is None


class TestModelTitle:
    async def test_first_message_names_session_with_generated_title(self, api_env: ApiEnv) -> None:
        import asyncio

        calls: list[str] = []

        async def fake_titler(_profile: object, message: str) -> str | None:
            calls.append(message)
            return "算法选题"

        api_env.app.state.turn_runner._title_generator = fake_titler
        pid = await _project(api_env)
        session = (
            await api_env.client.post(
                f"/api/projects/{pid}/stages/topic/sessions",
                json={"model_profile_id": _fake_profile_id(api_env)},
            )
        ).json()

        response = await api_env.client.post(
            f"/api/sessions/{session['id']}/messages", json={"text": "帮我想几个算法相关的选题"}
        )
        assert response.status_code == 202
        title: str | None = None
        for _ in range(100):
            title = (await api_env.client.get(f"/api/sessions/{session['id']}")).json()["title"]
            if title == "算法选题":
                break
            await asyncio.sleep(0.05)
        assert title == "算法选题"
        assert calls == ["帮我想几个算法相关的选题"]
