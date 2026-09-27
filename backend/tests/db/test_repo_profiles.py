from __future__ import annotations

from sqlalchemy import Engine

from studio.db.repo.profiles import (
    get_model_profile,
    list_model_profiles,
    seed_model_profiles,
)


def test_seed_without_fake_runtime_creates_four_profiles(migrated_engine: Engine) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    profiles = list_model_profiles(migrated_engine)
    names = {p.name for p in profiles}
    assert names == {"claude-sonnet", "claude-login", "gpt", "deepseek"}


def test_seed_with_fake_runtime_also_creates_fake_profile(migrated_engine: Engine) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=True)
    profiles = list_model_profiles(migrated_engine)
    names = {p.name for p in profiles}
    assert names == {"fake", "claude-sonnet", "claude-login", "gpt", "deepseek"}


def test_seed_is_idempotent(migrated_engine: Engine) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=True)
    seed_model_profiles(migrated_engine, enable_fake_runtime=True)
    profiles = list_model_profiles(migrated_engine)
    names = [p.name for p in profiles]
    assert len(names) == len(set(names)) == 5


def test_seed_claude_sonnet_profile_fields(migrated_engine: Engine) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    profile = get_model_profile(migrated_engine, "claude-sonnet")
    assert profile is not None
    assert profile.runtime == "claude"
    assert profile.model == "claude-sonnet-5"
    assert profile.api_key_env == "ANTHROPIC_API_KEY"


def test_seed_claude_login_profile_has_no_api_key_env(migrated_engine: Engine) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    profile = get_model_profile(migrated_engine, "claude-login")
    assert profile is not None
    assert profile.runtime == "claude"
    assert profile.model == "claude-sonnet-5"
    assert not profile.api_key_env


def test_seed_gpt_profile_fields(migrated_engine: Engine) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    profile = get_model_profile(migrated_engine, "gpt")
    assert profile is not None
    assert profile.runtime == "openai"
    assert profile.model == "gpt-5"
    assert profile.api_key_env == "OPENAI_API_KEY"


def test_seed_deepseek_profile_fields(migrated_engine: Engine) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    profile = get_model_profile(migrated_engine, "deepseek")
    assert profile is not None
    assert profile.runtime == "openai"
    assert profile.provider == "litellm"
    assert profile.model == "deepseek/deepseek-chat"
    assert profile.api_key_env == "DEEPSEEK_API_KEY"


def test_get_model_profile_unknown_name_returns_none(migrated_engine: Engine) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    assert get_model_profile(migrated_engine, "nope") is None


def test_list_model_profiles_returns_plain_values_not_orm(migrated_engine: Engine) -> None:
    from studio.db import models

    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    profiles = list_model_profiles(migrated_engine)
    assert profiles
    assert all(not isinstance(p, models.ModelProfile) for p in profiles)
