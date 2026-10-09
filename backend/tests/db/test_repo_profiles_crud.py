"""`model_profiles` 增改删（计划 M5 T6）：校验、内置配置保护、被引用时不能删、环境变量覆盖字段。"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, update

from studio.config import Settings
from studio.db.engine import session_scope
from studio.db.models import ModelProfile
from studio.db.repo.profiles import (
    BuiltinProfileError,
    DuplicateProfileError,
    ProfileInUseError,
    ProfileNotFoundError,
    ProfileValidationError,
    create_model_profile,
    delete_model_profile,
    env_override_fields,
    get_model_profile,
    get_model_profile_by_id,
    seed_model_profiles,
    update_model_profile,
)
from studio.db.repo.sessions import create_session
from studio.db.repo.settings import update_settings


def _fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "name": "my-gpt",
        "provider": "openai",
        "model": "gpt-5-mini",
        "runtime": "openai",
        "base_url": None,
        "api_key_env": "OPENAI_API_KEY",
        "supports_vision": True,
        "price_input": 0.25,
        "price_output": 2.0,
        "max_cost_per_turn": 0.5,
        "max_steps_per_turn": 30,
    }
    fields.update(overrides)
    return fields


class TestCreate:
    def test_creates_and_reads_back(self, migrated_engine: Engine) -> None:
        created = create_model_profile(migrated_engine, **_fields())

        got = get_model_profile_by_id(migrated_engine, created.id)
        assert got is not None
        assert got == created
        assert got.name == "my-gpt" and got.model == "gpt-5-mini"
        assert got.max_steps_per_turn == 30

    def test_optional_fields_can_be_empty(self, migrated_engine: Engine) -> None:
        created = create_model_profile(
            migrated_engine,
            **_fields(
                price_input=None, price_output=None, max_cost_per_turn=None, max_steps_per_turn=None
            ),
        )

        assert created.price_input is None and created.max_cost_per_turn is None
        assert created.max_steps_per_turn is None

    def test_claude_profile_may_use_the_local_login(self, migrated_engine: Engine) -> None:
        created = create_model_profile(
            migrated_engine,
            **_fields(name="my-login", provider="anthropic", runtime="claude", api_key_env=None),
        )

        assert created.api_key_env is None

    def test_zero_cost_budget_is_allowed(self, migrated_engine: Engine) -> None:
        assert (
            create_model_profile(migrated_engine, **_fields(max_cost_per_turn=0)).max_cost_per_turn
            == 0
        )

    def test_duplicate_name_is_rejected(self, migrated_engine: Engine) -> None:
        create_model_profile(migrated_engine, **_fields())
        with pytest.raises(DuplicateProfileError):
            create_model_profile(migrated_engine, **_fields())

    @pytest.mark.parametrize(
        ("override", "needle"),
        [
            ({"name": ""}, "名称"),
            ({"name": "has space"}, "名称"),
            ({"name": "x" * 51}, "名称"),
            ({"provider": " "}, "provider"),
            ({"model": ""}, "模型"),
            ({"runtime": "fake"}, "运行时"),
            ({"runtime": "gemini"}, "运行时"),
            ({"base_url": "ftp://example.com"}, "base_url"),
            ({"base_url": "not a url"}, "base_url"),
            ({"base_url": "https://user:secret@example.com/v1"}, "账号"),
            ({"api_key_env": "lower_case"}, "环境变量"),
            ({"api_key_env": "1BAD"}, "环境变量"),
            ({"api_key_env": "sk-abcdefghijklmnop"}, "环境变量"),
            ({"api_key_env": None}, "本机登录"),
            ({"price_input": -0.1}, "单价"),
            ({"price_output": float("inf")}, "单价"),
            ({"price_input": float("nan")}, "单价"),
            ({"max_cost_per_turn": -1}, "成本"),
            ({"max_steps_per_turn": 0}, "步数"),
            ({"max_steps_per_turn": -3}, "步数"),
            ({"max_steps_per_turn": 1.5}, "步数"),
            ({"supports_vision": "yes"}, "supports_vision"),
        ],
    )
    def test_invalid_values_are_rejected_and_nothing_is_stored(
        self, migrated_engine: Engine, override: dict[str, Any], needle: str
    ) -> None:
        with pytest.raises(ProfileValidationError) as info:
            create_model_profile(migrated_engine, **_fields(**override))

        assert needle in str(info.value)
        assert get_model_profile(migrated_engine, "my-gpt") is None

    def test_all_problems_are_listed_together(self, migrated_engine: Engine) -> None:
        with pytest.raises(ProfileValidationError) as info:
            create_model_profile(migrated_engine, **_fields(model="", price_input=-1))

        assert len(info.value.errors) == 2


class TestUpdate:
    def _created(self, engine: Engine) -> Any:
        return create_model_profile(engine, **_fields(base_url="https://gw.example.com/v1"))

    def test_changes_only_the_given_fields(self, migrated_engine: Engine) -> None:
        created = self._created(migrated_engine)

        updated = update_model_profile(
            migrated_engine, created.id, {"model": "gpt-5", "price_input": 1.25}
        )

        assert updated.model == "gpt-5" and updated.price_input == 1.25
        assert updated.price_output == 2.0
        assert updated.base_url == "https://gw.example.com/v1"
        assert updated.name == "my-gpt"

    def test_untouched_base_url_with_credentials_does_not_block_other_edits(
        self, migrated_engine: Engine
    ) -> None:
        """环境变量灌进库里的 base_url 可能带账号密码；只改预算时不该被它拒绝，改它自己仍要校验。"""
        seed_model_profiles(migrated_engine, enable_fake_runtime=False)
        gpt = get_model_profile(migrated_engine, "gpt")
        assert gpt is not None
        with session_scope(migrated_engine) as db:
            db.execute(
                update(ModelProfile)
                .where(ModelProfile.id == gpt.id)
                .values(base_url="https://user:key@gw.example.com/v1")
            )

        updated = update_model_profile(migrated_engine, gpt.id, {"max_steps_per_turn": 12})

        assert updated.max_steps_per_turn == 12
        assert updated.base_url == "https://user:key@gw.example.com/v1"
        with pytest.raises(ProfileValidationError, match="账号密码"):
            update_model_profile(
                migrated_engine, gpt.id, {"base_url": "https://a:b@other.example.com"}
            )

    def test_none_clears_nullable_fields(self, migrated_engine: Engine) -> None:
        created = self._created(migrated_engine)

        updated = update_model_profile(
            migrated_engine,
            created.id,
            {
                "base_url": None,
                "price_input": None,
                "price_output": None,
                "max_cost_per_turn": None,
                "max_steps_per_turn": None,
            },
        )

        assert updated.base_url is None
        assert (updated.price_input, updated.price_output) == (None, None)
        assert (updated.max_cost_per_turn, updated.max_steps_per_turn) == (None, None)

    def test_api_key_env_can_be_cleared_only_for_claude(self, migrated_engine: Engine) -> None:
        openai = self._created(migrated_engine)
        with pytest.raises(ProfileValidationError, match="本机登录"):
            update_model_profile(migrated_engine, openai.id, {"api_key_env": None})
        claude = create_model_profile(
            migrated_engine,
            **_fields(
                name="c", provider="anthropic", runtime="claude", api_key_env="ANTHROPIC_API_KEY"
            ),
        )

        assert (
            update_model_profile(migrated_engine, claude.id, {"api_key_env": None}).api_key_env
            is None
        )

    @pytest.mark.parametrize("field", ["name", "provider", "runtime", "id", "nope"])
    def test_immutable_or_unknown_fields_are_rejected(
        self, migrated_engine: Engine, field: str
    ) -> None:
        created = self._created(migrated_engine)

        with pytest.raises(ProfileValidationError, match=field):
            update_model_profile(migrated_engine, created.id, {field: "x"})

    def test_invalid_patch_changes_nothing(self, migrated_engine: Engine) -> None:
        created = self._created(migrated_engine)

        with pytest.raises(ProfileValidationError):
            update_model_profile(migrated_engine, created.id, {"model": "new", "price_input": -1})

        assert get_model_profile_by_id(migrated_engine, created.id) == created

    def test_builtin_profiles_can_be_edited(self, migrated_engine: Engine) -> None:
        seed_model_profiles(migrated_engine, enable_fake_runtime=False)
        gpt = get_model_profile(migrated_engine, "gpt")
        assert gpt is not None

        updated = update_model_profile(
            migrated_engine, gpt.id, {"model": "gpt-5.1", "max_steps_per_turn": 12}
        )

        assert updated.model == "gpt-5.1" and updated.max_steps_per_turn == 12

    def test_unknown_id(self, migrated_engine: Engine) -> None:
        with pytest.raises(ProfileNotFoundError):
            update_model_profile(migrated_engine, "nope", {"model": "x"})


class TestDelete:
    def test_custom_profile_can_be_deleted(self, migrated_engine: Engine) -> None:
        created = create_model_profile(migrated_engine, **_fields())

        delete_model_profile(migrated_engine, created.id)

        assert get_model_profile_by_id(migrated_engine, created.id) is None

    def test_builtin_profiles_cannot_be_deleted(self, migrated_engine: Engine) -> None:
        seed_model_profiles(migrated_engine, enable_fake_runtime=True)
        for name in ("claude-sonnet", "claude-login", "gpt", "deepseek", "fake"):
            profile = get_model_profile(migrated_engine, name)
            assert profile is not None
            with pytest.raises(BuiltinProfileError):
                delete_model_profile(migrated_engine, profile.id)
            assert get_model_profile(migrated_engine, name) is not None

    def test_profile_used_by_a_session_cannot_be_deleted(self, migrated_engine: Engine) -> None:
        created = create_model_profile(migrated_engine, **_fields())
        for _ in range(2):
            create_session(
                migrated_engine,
                project_id=None,
                stage="brainstorm",
                model_profile_id=created.id,
                runtime="openai",
            )

        with pytest.raises(ProfileInUseError) as info:
            delete_model_profile(migrated_engine, created.id)

        assert info.value.session_count == 2
        assert "2 个会话" in str(info.value)
        assert get_model_profile_by_id(migrated_engine, created.id) is not None

    def test_profile_used_as_a_stage_default_cannot_be_deleted(
        self, migrated_engine: Engine
    ) -> None:
        created = create_model_profile(migrated_engine, **_fields())
        update_settings(
            migrated_engine,
            {"stage_default_profile": {"topic": created.id, "animation_html": created.id}},
        )

        with pytest.raises(ProfileInUseError) as info:
            delete_model_profile(migrated_engine, created.id)

        assert info.value.stages == ["topic", "animation_html"]
        assert "topic" in str(info.value)

    def test_unknown_id(self, migrated_engine: Engine) -> None:
        with pytest.raises(ProfileNotFoundError):
            delete_model_profile(migrated_engine, "nope")


def _settings(**overrides: Any) -> Settings:
    """不读 `backend/.env` 和进程环境的 `Settings`（开发机上的网关配置不能影响断言）。"""
    fields: dict[str, Any] = {
        "anthropic_base_url": None,
        "openai_base_url": None,
        "openai_model": None,
        "openai_price_input": None,
        "openai_price_output": None,
    }
    return Settings.model_construct(**{**fields, **overrides})


class TestEnvOverrideFields:
    def test_none_without_settings(self) -> None:
        assert env_override_fields("gpt", None) == []
        assert env_override_fields("gpt", _settings()) == []

    def test_lists_only_the_fields_the_environment_sets(self) -> None:
        settings = _settings(
            openai_base_url="https://openrouter.ai/api/v1",
            openai_model="openai/gpt-5",
            anthropic_base_url="http://localhost:1234",
        )

        assert env_override_fields("gpt", settings) == ["base_url", "model"]
        assert env_override_fields("claude-sonnet", settings) == ["base_url"]
        assert env_override_fields("claude-login", settings) == []
        assert env_override_fields("deepseek", settings) == []
        assert env_override_fields("my-custom", settings) == []

    def test_prices_are_overridable_for_gpt(self) -> None:
        settings = _settings(openai_price_input=0.5, openai_price_output=4.0)

        assert env_override_fields("gpt", settings) == ["price_input", "price_output"]
