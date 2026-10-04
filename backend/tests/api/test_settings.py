"""`/api/settings`（计划 M5 T1）：读取带默认值，写入校验，非法值不落库。"""

from __future__ import annotations

from typing import Any

import pytest

from studio.db.repo.profiles import get_model_profile
from studio.db.repo.settings import get_all_settings

from .conftest import ApiEnv, assert_detail


async def _profile_id(api_env: ApiEnv, name: str) -> str:
    profile = get_model_profile(api_env.app.state.engine, name)
    assert profile is not None
    return profile.id


async def _patch(api_env: ApiEnv, body: dict[str, Any]) -> Any:
    return await api_env.client.patch("/api/settings", json=body)


class TestGetSettings:
    async def test_defaults(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/settings")

        assert response.status_code == 200
        assert response.json() == {
            "stage_default_profile": {},
            "web_mode": "tools",
            "web_mode_source": "env",
            "web_mode_env": "tools",
            "tts_default": {"voice": "zizi", "speech_rate": 1.0},
            "default_style_preset_id": None,
        }


class TestPatchSettings:
    async def test_web_mode_override_and_clear(self, api_env: ApiEnv) -> None:
        response = await _patch(api_env, {"web_mode": "native"})
        assert response.status_code == 200
        body = response.json()
        assert (body["web_mode"], body["web_mode_source"], body["web_mode_env"]) == (
            "native",
            "ui",
            "tools",
        )

        response = await _patch(api_env, {"web_mode": None})
        body = response.json()
        assert (body["web_mode"], body["web_mode_source"]) == ("tools", "env")
        assert get_all_settings(api_env.app.state.engine).web_mode is None

    async def test_stage_default_profile_round_trip(self, api_env: ApiEnv) -> None:
        fake_id = await _profile_id(api_env, "fake")
        login_id = await _profile_id(api_env, "claude-login")

        response = await _patch(
            api_env, {"stage_default_profile": {"topic": fake_id, "brainstorm": login_id}}
        )

        assert response.status_code == 200
        assert response.json()["stage_default_profile"] == {
            "topic": fake_id,
            "brainstorm": login_id,
        }

        response = await _patch(api_env, {"stage_default_profile": {"topic": None}})
        assert response.json()["stage_default_profile"] == {"brainstorm": login_id}

    async def test_the_style_stage_can_have_a_default_model(self, api_env: ApiEnv) -> None:
        fake_id = await _profile_id(api_env, "fake")

        response = await _patch(api_env, {"stage_default_profile": {"style": fake_id}})

        assert response.status_code == 200
        assert response.json()["stage_default_profile"] == {"style": fake_id}

    async def test_the_html_animation_stage_can_have_a_default_model(self, api_env: ApiEnv) -> None:
        fake_id = await _profile_id(api_env, "fake")

        response = await _patch(api_env, {"stage_default_profile": {"animation_html": fake_id}})

        assert response.status_code == 200
        assert response.json()["stage_default_profile"] == {"animation_html": fake_id}

    async def test_tts_default_round_trip_and_partial(self, api_env: ApiEnv) -> None:
        response = await _patch(api_env, {"tts_default": {"voice": "xiaohe", "speech_rate": 1.2}})
        assert response.json()["tts_default"] == {"voice": "xiaohe", "speech_rate": 1.2}

        response = await _patch(api_env, {"tts_default": {"speech_rate": 0.8}})
        assert response.json()["tts_default"] == {"voice": "xiaohe", "speech_rate": 0.8}

        response = await _patch(api_env, {"tts_default": {"voice": None, "speech_rate": None}})
        assert response.json()["tts_default"] == {"voice": "zizi", "speech_rate": 1.0}

    @pytest.mark.parametrize(
        ("body", "needle"),
        [
            ({"web_mode": "auto"}, "web_mode"),
            ({"nope": 1}, "nope"),
            ({"stage_default_profile": {"publish": "x"}}, "未知阶段"),
            ({"tts_default": {"speech_rate": 3}}, "语速"),
            ({"tts_default": {"voice": "not-a-voice"}}, "音色"),
        ],
    )
    async def test_invalid_values_are_422_and_persist_nothing(
        self, api_env: ApiEnv, body: dict[str, Any], needle: str
    ) -> None:
        response = await _patch(api_env, {"web_mode": "native", **body})

        assert response.status_code == 422
        assert needle in str(assert_detail(response))
        assert get_all_settings(api_env.app.state.engine).web_mode is None

    async def test_unknown_profile_is_422(self, api_env: ApiEnv) -> None:
        response = await _patch(api_env, {"stage_default_profile": {"topic": "missing"}})

        assert response.status_code == 422
        assert "模型配置不存在" in assert_detail(response)

    async def test_profile_without_configured_key_is_422(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        profile_id = await _profile_id(api_env, "claude-sonnet")

        response = await _patch(api_env, {"stage_default_profile": {"topic": profile_id}})

        assert response.status_code == 422
        assert "密钥" in assert_detail(response)
        assert get_all_settings(api_env.app.state.engine).stage_default_profile == {}

    async def test_profile_with_disabled_runtime_is_422(self, api_env: ApiEnv) -> None:
        profile_id = await _profile_id(api_env, "fake")
        api_env.app.state.runtime_factory._constructors.pop("fake")

        response = await _patch(api_env, {"stage_default_profile": {"topic": profile_id}})

        assert response.status_code == 422
        assert "运行时未启用" in assert_detail(response)
