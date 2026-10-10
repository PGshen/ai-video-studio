"""`/api/model-profiles`：列表、增改删（任务简报 T7；计划 M5 T6）。

响应返回 `api_key_env`（环境变量的**名字**，界面要编辑它）和 `base_url`，但永远不含 key 的值，
只返回是否已配置（M5 T6 决策 D10：改变了 T7 时「不返回环境变量名」的做法）。
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import update

from studio.agent.probe import ProbeResult
from studio.agent.runtime import RuntimeFactory
from studio.db.engine import session_scope
from studio.db.models import ModelProfile
from studio.db.repo.profiles import ModelProfileValue, get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.settings import update_settings

from .conftest import ApiEnv, assert_detail


class TestListModelProfiles:
    async def test_lists_seeded_profiles(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/model-profiles")

        assert response.status_code == 200
        names = {p["name"] for p in response.json()}
        assert {"fake", "claude-sonnet", "claude-login", "gpt", "deepseek"} <= names

    async def test_exposes_env_var_names_but_never_key_values(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-super-secret-value")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-another-secret-value")

        response = await api_env.client.get("/api/model-profiles")

        assert "sk-super-secret-value" not in response.text
        assert "sk-another-secret-value" not in response.text
        by_name = {p["name"]: p for p in response.json()}
        assert by_name["claude-sonnet"]["api_key_env"] == "ANTHROPIC_API_KEY"
        assert by_name["claude-login"]["api_key_env"] is None
        for profile in by_name.values():
            assert "api_key" not in profile

    async def test_marks_builtin_profiles(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)

        response = await api_env.client.get("/api/model-profiles")

        by_name = {p["name"]: p for p in response.json()}
        assert by_name["gpt"]["builtin"] is True
        assert by_name["fake"]["builtin"] is True
        assert by_name[created["name"]]["builtin"] is False

    async def test_base_url_is_listed_with_credentials_masked(self, api_env: ApiEnv) -> None:
        engine = api_env.app.state.engine
        with session_scope(engine) as db:
            db.execute(
                update(ModelProfile)
                .where(ModelProfile.name == "deepseek")
                .values(base_url="https://user:hunter2@gw.example.com/v1")
            )

        response = await api_env.client.get("/api/model-profiles")

        assert "hunter2" not in response.text
        by_name = {p["name"]: p for p in response.json()}
        assert by_name["deepseek"]["base_url"] == "https://***@gw.example.com/v1"

    async def test_key_configured_reflects_env_var(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        response = await api_env.client.get("/api/model-profiles")
        by_name = {p["name"]: p for p in response.json()}
        assert by_name["claude-sonnet"]["key_configured"] is False

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        response = await api_env.client.get("/api/model-profiles")
        by_name = {p["name"]: p for p in response.json()}
        assert by_name["claude-sonnet"]["key_configured"] is True

    async def test_login_profile_needs_no_key(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/model-profiles")
        by_name = {p["name"]: p for p in response.json()}
        assert by_name["claude-login"]["key_configured"] is True

    async def test_fake_profile_needs_no_key(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/model-profiles")
        by_name = {p["name"]: p for p in response.json()}
        assert by_name["fake"]["key_configured"] is True

    async def test_env_override_lists_fields_decided_by_the_environment(
        self, api_env: ApiEnv
    ) -> None:
        # `api_env` 的 Settings 会读开发机的 backend/.env，先把网关字段清空，断言才不依赖它。
        settings = api_env.app.state.settings
        for name in (
            "anthropic_base_url",
            "openai_base_url",
            "openai_model",
            "openai_price_input",
            "openai_price_output",
        ):
            setattr(settings, name, None)
        response = await api_env.client.get("/api/model-profiles")
        assert all(p["env_override"] == [] for p in response.json())

        settings.openai_base_url = "https://openrouter.ai/api/v1"
        settings.openai_model = "openai/gpt-5"
        response = await api_env.client.get("/api/model-profiles")
        by_name = {p["name"]: p for p in response.json()}
        assert by_name["gpt"]["env_override"] == ["base_url", "model"]
        assert by_name["deepseek"]["env_override"] == []


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "my-gpt",
        "provider": "openai",
        "model": "gpt-5-mini",
        "runtime": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "supports_vision": True,
        "price_input": 0.25,
        "price_output": 2.0,
        "max_cost_per_turn": 0.5,
        "max_steps_per_turn": 30,
    }
    body.update(overrides)
    return body


async def _create(api_env: ApiEnv, **overrides: Any) -> dict[str, Any]:
    response = await api_env.client.post("/api/model-profiles", json=_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


class TestCreate:
    async def test_creates_a_profile_that_shows_up_in_the_list(self, api_env: ApiEnv) -> None:
        created = await _create(api_env, base_url="https://gw.example.com/v1")

        assert created["name"] == "my-gpt"
        assert created["builtin"] is False
        assert created["base_url"] == "https://gw.example.com/v1"
        assert created["api_key_env"] == "OPENAI_API_KEY"
        listing = await api_env.client.get("/api/model-profiles")
        assert created["id"] in {p["id"] for p in listing.json()}

    async def test_duplicate_name_is_409(self, api_env: ApiEnv) -> None:
        await _create(api_env)

        response = await api_env.client.post("/api/model-profiles", json=_body())

        assert response.status_code == 409

    @pytest.mark.parametrize(
        ("override", "needle"),
        [
            ({"runtime": "fake"}, "运行时"),
            ({"runtime": "gemini"}, "运行时"),
            ({"price_input": -1}, "单价"),
            ({"max_steps_per_turn": 0}, "步数"),
            ({"api_key_env": "not-an-env-name"}, "环境变量"),
            ({"base_url": "https://u:p@example.com"}, "账号"),
        ],
    )
    async def test_invalid_values_are_422_and_named(
        self, api_env: ApiEnv, override: dict[str, Any], needle: str
    ) -> None:
        response = await api_env.client.post("/api/model-profiles", json=_body(**override))

        assert response.status_code == 422
        assert needle in str(assert_detail(response))
        assert get_model_profile(api_env.app.state.engine, "my-gpt") is None

    async def test_unregistered_runtime_is_422(self, api_env: ApiEnv) -> None:
        api_env.app.state.runtime_factory._constructors.pop("openai")

        response = await api_env.client.post("/api/model-profiles", json=_body())

        assert response.status_code == 422
        assert "运行时未启用" in assert_detail(response)

    async def test_unknown_body_fields_are_rejected(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post("/api/model-profiles", json=_body(api_key="sk-oops"))

        assert response.status_code == 422


class TestPatch:
    async def test_updates_only_the_given_fields(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)

        response = await api_env.client.patch(
            f"/api/model-profiles/{created['id']}",
            json={"model": "gpt-5", "max_cost_per_turn": None},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["model"] == "gpt-5"
        assert body["max_cost_per_turn"] is None
        assert body["price_input"] == 0.25

    async def test_name_provider_and_runtime_cannot_change(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)

        for field in ("name", "provider", "runtime"):
            response = await api_env.client.patch(
                f"/api/model-profiles/{created['id']}", json={field: "x"}
            )
            assert response.status_code == 422, field

    async def test_invalid_value_is_422_and_changes_nothing(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)

        response = await api_env.client.patch(
            f"/api/model-profiles/{created['id']}", json={"model": "x", "price_input": -5}
        )

        assert response.status_code == 422
        listing = await api_env.client.get("/api/model-profiles")
        current = {p["id"]: p for p in listing.json()}[created["id"]]
        assert current["model"] == "gpt-5-mini"

    async def test_fields_decided_by_the_environment_cannot_be_edited(
        self, api_env: ApiEnv
    ) -> None:
        api_env.app.state.settings.openai_model = "openai/gpt-5"
        listing = await api_env.client.get("/api/model-profiles")
        gpt = next(p for p in listing.json() if p["name"] == "gpt")

        response = await api_env.client.patch(
            f"/api/model-profiles/{gpt['id']}", json={"model": "x"}
        )

        assert response.status_code == 422
        assert "环境变量" in assert_detail(response)
        assert ".env" in assert_detail(response)

    async def test_other_fields_of_an_env_overridden_profile_are_editable(
        self, api_env: ApiEnv
    ) -> None:
        api_env.app.state.settings.openai_model = "openai/gpt-5"
        listing = await api_env.client.get("/api/model-profiles")
        gpt = next(p for p in listing.json() if p["name"] == "gpt")

        response = await api_env.client.patch(
            f"/api/model-profiles/{gpt['id']}", json={"max_steps_per_turn": 9}
        )

        assert response.status_code == 200
        assert response.json()["max_steps_per_turn"] == 9

    async def test_unknown_id_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.patch("/api/model-profiles/nope", json={"model": "x"})

        assert response.status_code == 404


class TestDelete:
    async def test_deletes_a_custom_profile(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)

        response = await api_env.client.delete(f"/api/model-profiles/{created['id']}")

        assert response.status_code == 204
        listing = await api_env.client.get("/api/model-profiles")
        assert created["id"] not in {p["id"] for p in listing.json()}

    async def test_builtin_profile_is_409(self, api_env: ApiEnv) -> None:
        profile = get_model_profile(api_env.app.state.engine, "gpt")
        assert profile is not None

        response = await api_env.client.delete(f"/api/model-profiles/{profile.id}")

        assert response.status_code == 409
        assert "内置" in assert_detail(response)

    async def test_profile_used_by_sessions_is_409_with_the_count(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)
        for _ in range(3):
            create_session(
                api_env.app.state.engine,
                project_id=None,
                stage="brainstorm",
                model_profile_id=created["id"],
                runtime="openai",
            )

        response = await api_env.client.delete(f"/api/model-profiles/{created['id']}")

        assert response.status_code == 409
        assert "3 个会话" in assert_detail(response)

    async def test_profile_used_as_stage_default_is_409(self, api_env: ApiEnv) -> None:
        created = await _create(api_env)
        update_settings(
            api_env.app.state.engine, {"stage_default_profile": {"topic": created["id"]}}
        )

        response = await api_env.client.delete(f"/api/model-profiles/{created['id']}")

        assert response.status_code == 409
        assert "topic" in assert_detail(response)

    async def test_unknown_id_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.delete("/api/model-profiles/nope")

        assert response.status_code == 404


async def _profile_id(api_env: ApiEnv, name: str) -> str:
    profile = get_model_profile(api_env.app.state.engine, name)
    assert profile is not None
    return profile.id


class TestProbe:
    async def test_fake_profile_succeeds_with_the_real_probe(self, api_env: ApiEnv) -> None:
        profile_id = await _profile_id(api_env, "fake")

        response = await api_env.client.post(f"/api/model-profiles/{profile_id}/test")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert set(body) == {"ok", "latency_ms", "reply", "error"}

    async def test_delegates_to_the_probe_with_the_saved_profile(self, api_env: ApiEnv) -> None:
        seen: list[ModelProfileValue] = []

        async def probe(profile: ModelProfileValue) -> ProbeResult:
            seen.append(profile)
            return ProbeResult(ok=False, latency_ms=812, reply=None, error="401 invalid key")

        api_env.app.state.probe = probe
        profile_id = await _profile_id(api_env, "claude-login")

        response = await api_env.client.post(f"/api/model-profiles/{profile_id}/test")

        assert response.status_code == 200
        assert response.json() == {
            "ok": False,
            "latency_ms": 812,
            "reply": None,
            "error": "401 invalid key",
        }
        assert [p.name for p in seen] == ["claude-login"]

    async def test_unregistered_runtime_fails_without_probing(self, api_env: ApiEnv) -> None:
        async def probe(profile: ModelProfileValue) -> ProbeResult:
            raise AssertionError("不应发请求")

        api_env.app.state.probe = probe
        api_env.app.state.runtime_factory = RuntimeFactory()  # 什么运行时都没启用
        profile_id = await _profile_id(api_env, "fake")

        response = await api_env.client.post(f"/api/model-profiles/{profile_id}/test")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "运行时未启用" in body["error"]

    async def test_unknown_profile_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post("/api/model-profiles/nope/test")

        assert response.status_code == 404
