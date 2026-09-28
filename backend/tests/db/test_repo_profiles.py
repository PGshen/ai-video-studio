from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import cast

from sqlalchemy import Engine

from studio.config import Settings
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
    # deepseek-chat stopped resolving on 2026-07-24; deepseek-flash is the current name.
    assert profile.model == "deepseek/deepseek-flash"
    assert profile.api_key_env == "DEEPSEEK_API_KEY"


def test_seed_prices_per_million_tokens(migrated_engine: Engine) -> None:
    """Official list prices checked 2026-09-28 (USD / 1M tokens, standard tier;
    DeepSeek at peak rates so the cost estimate never undershoots)."""
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    expected = {
        "claude-sonnet": (2.0, 10.0),
        "claude-login": (2.0, 10.0),
        "gpt": (1.25, 10.0),
        "deepseek": (0.30, 1.20),
    }
    for name, (price_in, price_out) in expected.items():
        profile = get_model_profile(migrated_engine, name)
        assert profile is not None
        assert (profile.price_input, profile.price_output) == (price_in, price_out), name


def test_seed_supports_vision_flags(migrated_engine: Engine) -> None:
    """R2（2026-09-28 冒烟 run2/run3，docs/references/openai-agents-sdk.md）：
    deepseek-flash 不支持图片输入，种子改为 supports_vision=False；其余三个仍为真。"""
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    expected = {
        "claude-sonnet": True,
        "claude-login": True,
        "gpt": True,
        "deepseek": False,
    }
    for name, supports_vision in expected.items():
        profile = get_model_profile(migrated_engine, name)
        assert profile is not None
        assert profile.supports_vision is supports_vision, name


def test_get_model_profile_unknown_name_returns_none(migrated_engine: Engine) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    assert get_model_profile(migrated_engine, "nope") is None


def test_list_model_profiles_returns_plain_values_not_orm(migrated_engine: Engine) -> None:
    from studio.db import models

    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    profiles = list_model_profiles(migrated_engine)
    assert profiles
    assert all(not isinstance(p, models.ModelProfile) for p in profiles)


# ---- gateway overrides from Settings (F2) --------------------------------------


def _settings(tmp_path: Path, **values: str | float) -> Settings:
    # Explicit None beats whatever backend/.env holds, so tests stay hermetic.
    return Settings(
        data_dir=tmp_path / "data",
        anthropic_base_url=cast("str | None", values.get("anthropic_base_url")),
        openai_base_url=cast("str | None", values.get("openai_base_url")),
        openai_model=cast("str | None", values.get("openai_model")),
        openai_price_input=cast("float | None", values.get("openai_price_input")),
        openai_price_output=cast("float | None", values.get("openai_price_output")),
    )


_GATEWAYS = {
    "anthropic_base_url": "https://anthropic-gw.example",
    "openai_base_url": "https://openrouter.example/api/v1",
    "openai_model": "openai/gpt-5",
}


def test_seed_applies_gateway_settings_to_new_rows(migrated_engine: Engine, tmp_path: Path) -> None:
    seed_model_profiles(
        migrated_engine, enable_fake_runtime=False, settings=_settings(tmp_path, **_GATEWAYS)
    )
    sonnet = get_model_profile(migrated_engine, "claude-sonnet")
    login = get_model_profile(migrated_engine, "claude-login")
    gpt = get_model_profile(migrated_engine, "gpt")
    deepseek = get_model_profile(migrated_engine, "deepseek")
    assert sonnet is not None and login is not None and gpt is not None and deepseek is not None
    assert sonnet.base_url == "https://anthropic-gw.example"
    assert login.base_url is None  # login mode talks to Anthropic with the local account
    assert (gpt.base_url, gpt.model) == ("https://openrouter.example/api/v1", "openai/gpt-5")
    assert (deepseek.base_url, deepseek.model) == (None, "deepseek/deepseek-flash")


def test_seed_without_gateway_settings_keeps_defaults(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False, settings=_settings(tmp_path))
    gpt = get_model_profile(migrated_engine, "gpt")
    sonnet = get_model_profile(migrated_engine, "claude-sonnet")
    assert gpt is not None and sonnet is not None
    assert (gpt.base_url, gpt.model) == (None, "gpt-5")
    assert sonnet.base_url is None


def test_seed_updates_existing_rows_only_for_configured_fields(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    before = {p.name: p for p in list_model_profiles(migrated_engine)}

    seed_model_profiles(
        migrated_engine, enable_fake_runtime=False, settings=_settings(tmp_path, **_GATEWAYS)
    )
    after = {p.name: p for p in list_model_profiles(migrated_engine)}

    assert after["claude-sonnet"] == dataclasses.replace(
        before["claude-sonnet"], base_url="https://anthropic-gw.example"
    )
    assert after["gpt"] == dataclasses.replace(
        before["gpt"], base_url="https://openrouter.example/api/v1", model="openai/gpt-5"
    )
    assert after["claude-login"] == before["claude-login"]
    assert after["deepseek"] == before["deepseek"]


def test_seed_empty_setting_does_not_clear_existing_value(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    seed_model_profiles(
        migrated_engine, enable_fake_runtime=False, settings=_settings(tmp_path, **_GATEWAYS)
    )
    seed_model_profiles(migrated_engine, enable_fake_runtime=False, settings=_settings(tmp_path))
    gpt = get_model_profile(migrated_engine, "gpt")
    assert gpt is not None
    assert (gpt.base_url, gpt.model) == ("https://openrouter.example/api/v1", "openai/gpt-5")


# ---- gpt price overrides from Settings (G2) -------------------------------------

_PRICES: dict[str, str | float] = {
    "openai_price_input": 0.10,
    "openai_price_output": 0.50,
}


def test_seed_applies_price_settings_to_new_gpt_row(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    seed_model_profiles(
        migrated_engine, enable_fake_runtime=False, settings=_settings(tmp_path, **_PRICES)
    )
    gpt = get_model_profile(migrated_engine, "gpt")
    sonnet = get_model_profile(migrated_engine, "claude-sonnet")
    assert gpt is not None and sonnet is not None
    assert (gpt.price_input, gpt.price_output) == (0.10, 0.50)
    # Only the gpt row is affected; other seeds keep their default prices.
    assert (sonnet.price_input, sonnet.price_output) == (2.0, 10.0)


def test_seed_without_price_settings_keeps_default_gpt_price(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False, settings=_settings(tmp_path))
    gpt = get_model_profile(migrated_engine, "gpt")
    assert gpt is not None
    assert (gpt.price_input, gpt.price_output) == (1.25, 10.0)


def test_seed_updates_existing_gpt_row_price_only_when_configured(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    seed_model_profiles(migrated_engine, enable_fake_runtime=False)
    before = {p.name: p for p in list_model_profiles(migrated_engine)}

    seed_model_profiles(
        migrated_engine, enable_fake_runtime=False, settings=_settings(tmp_path, **_PRICES)
    )
    after = {p.name: p for p in list_model_profiles(migrated_engine)}

    assert after["gpt"] == dataclasses.replace(before["gpt"], price_input=0.10, price_output=0.50)
    # base_url/model untouched since no gateway settings were provided this time.
    assert after["gpt"].base_url == before["gpt"].base_url
    assert after["gpt"].model == before["gpt"].model
    assert after["claude-sonnet"] == before["claude-sonnet"]


def test_seed_empty_price_setting_does_not_clear_existing_price(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    seed_model_profiles(
        migrated_engine, enable_fake_runtime=False, settings=_settings(tmp_path, **_PRICES)
    )
    seed_model_profiles(migrated_engine, enable_fake_runtime=False, settings=_settings(tmp_path))
    gpt = get_model_profile(migrated_engine, "gpt")
    assert gpt is not None
    assert (gpt.price_input, gpt.price_output) == (0.10, 0.50)
