"""`settings` 仓储（计划 M5 T1）：带类型的键、整体校验、清除与回落。"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, select

from studio.db.engine import session_scope
from studio.db.models import Setting
from studio.db.repo.settings import (
    SettingsValidationError,
    effective_web_mode,
    get_all_settings,
    update_settings,
    web_mode_override,
)


def _stored_keys(engine: Engine) -> set[str]:
    with session_scope(engine) as db:
        return {row.key for row in db.scalars(select(Setting))}


def test_retired_stage_defaults_are_ignored_on_read(migrated_engine: Engine) -> None:
    """Manim is retired (ADR 0027): a stored `animation` default must not reach readers."""
    with session_scope(migrated_engine) as db:
        db.add(Setting(key="stage_default_profile", value={"topic": "p1", "animation": "p2"}))

    assert get_all_settings(migrated_engine).stage_default_profile == {"topic": "p1"}
    with pytest.raises(SettingsValidationError):
        update_settings(migrated_engine, {"stage_default_profile": {"animation": "p2"}})


def test_defaults_when_nothing_is_stored(migrated_engine: Engine) -> None:
    value = get_all_settings(migrated_engine)

    assert value.stage_default_profile == {}
    assert value.web_mode is None
    assert value.tts_voice is None
    assert value.tts_speech_rate is None
    assert value.default_style_preset_id is None


def test_each_key_round_trips(migrated_engine: Engine) -> None:
    update_settings(
        migrated_engine,
        {
            "stage_default_profile": {"topic": "p1", "animation_html": "p2"},
            "web_mode": "native",
            "tts_default": {"voice": "xiaohe", "speech_rate": 1.25},
            "default_style_preset_id": "s1",
        },
    )

    value = get_all_settings(migrated_engine)
    assert value.stage_default_profile == {"topic": "p1", "animation_html": "p2"}
    assert value.web_mode == "native"
    assert value.tts_voice == "xiaohe"
    assert value.tts_speech_rate == 1.25
    assert value.default_style_preset_id == "s1"


def test_partial_update_leaves_other_keys_alone(migrated_engine: Engine) -> None:
    update_settings(
        migrated_engine,
        {"web_mode": "native", "tts_default": {"voice": "zizi", "speech_rate": 1.0}},
    )

    update_settings(migrated_engine, {"stage_default_profile": {"topic": "p1"}})
    update_settings(migrated_engine, {"stage_default_profile": {"narrative": "p2"}})
    update_settings(migrated_engine, {"tts_default": {"speech_rate": 1.5}})

    value = get_all_settings(migrated_engine)
    assert value.stage_default_profile == {"topic": "p1", "narrative": "p2"}
    assert value.web_mode == "native"
    assert value.tts_voice == "zizi"
    assert value.tts_speech_rate == 1.5


def test_null_clears_a_key_and_its_row(migrated_engine: Engine) -> None:
    update_settings(
        migrated_engine,
        {
            "stage_default_profile": {"topic": "p1", "animation_html": "p2"},
            "web_mode": "native",
            "tts_default": {"voice": "zizi"},
            "default_style_preset_id": "s1",
        },
    )

    update_settings(
        migrated_engine,
        {
            "stage_default_profile": {"topic": None},
            "web_mode": None,
            "tts_default": {"voice": None},
            "default_style_preset_id": None,
        },
    )

    value = get_all_settings(migrated_engine)
    assert value.stage_default_profile == {"animation_html": "p2"}
    assert value.web_mode is None
    assert value.tts_voice is None
    assert value.default_style_preset_id is None
    assert _stored_keys(migrated_engine) == {"stage_default_profile"}


@pytest.mark.parametrize(
    "patch",
    [
        {"nope": 1},
        {"stage_default_profile": {"publish": "p1"}},
        {"stage_default_profile": {"topic": ""}},
        {"stage_default_profile": {"topic": 3}},
        {"stage_default_profile": ["topic"]},
        {"web_mode": "auto"},
        {"web_mode": 1},
        {"tts_default": {"speed": 1.0}},
        {"tts_default": {"voice": ""}},
        {"tts_default": {"speech_rate": 0.49}},
        {"tts_default": {"speech_rate": 2.01}},
        {"tts_default": {"speech_rate": True}},
        {"tts_default": {"speech_rate": "fast"}},
        {"default_style_preset_id": ""},
        {"default_style_preset_id": 7},
    ],
)
def test_invalid_values_are_rejected(migrated_engine: Engine, patch: dict[str, object]) -> None:
    with pytest.raises(SettingsValidationError):
        update_settings(migrated_engine, patch)

    assert _stored_keys(migrated_engine) == set()


def test_a_bad_value_writes_nothing_even_if_other_keys_are_valid(migrated_engine: Engine) -> None:
    with pytest.raises(SettingsValidationError):
        update_settings(
            migrated_engine,
            {"web_mode": "native", "tts_default": {"speech_rate": 99}},
        )

    assert _stored_keys(migrated_engine) == set()


def test_speech_rate_bounds_are_inclusive(migrated_engine: Engine) -> None:
    update_settings(migrated_engine, {"tts_default": {"speech_rate": 0.5}})
    assert get_all_settings(migrated_engine).tts_speech_rate == 0.5
    update_settings(migrated_engine, {"tts_default": {"speech_rate": 2}})
    assert get_all_settings(migrated_engine).tts_speech_rate == 2.0


def test_effective_web_mode_prefers_the_ui_override(migrated_engine: Engine) -> None:
    assert effective_web_mode(migrated_engine, "tools") == "tools"
    assert web_mode_override(migrated_engine) is None

    update_settings(migrated_engine, {"web_mode": "native"})
    assert effective_web_mode(migrated_engine, "tools") == "native"
    assert web_mode_override(migrated_engine) == "native"

    update_settings(migrated_engine, {"web_mode": None})
    assert effective_web_mode(migrated_engine, "native") == "native"
    assert effective_web_mode(migrated_engine, "tools") == "tools"
