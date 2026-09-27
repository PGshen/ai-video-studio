"""`/api/model-profiles`（任务简报 T7）：不返回 key，只返回是否已配置。"""

from __future__ import annotations

import pytest

from .conftest import ApiEnv


class TestListModelProfiles:
    async def test_lists_seeded_profiles_without_leaking_key_env_name(
        self, api_env: ApiEnv
    ) -> None:
        response = await api_env.client.get("/api/model-profiles")

        assert response.status_code == 200
        body = response.json()
        names = {p["name"] for p in body}
        assert {"fake", "claude-sonnet", "claude-login", "gpt", "deepseek"} <= names
        for profile in body:
            assert "api_key_env" not in profile
            assert "api_key" not in profile

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
