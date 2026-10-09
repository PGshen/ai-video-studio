"""`/api/settings`：各阶段默认模型、联网模式、新项目默认音色/语速、默认风格（计划 M5 T1）、
无隔离执行开关（ADR 0024，windows-native T6）。

补丁语义（`PATCH`）：只改请求里出现的字段，`null` 清除。形状校验在 `db.repo.settings`；
这里补上引用其他资源的检查——模型配置存在、运行时已启用、key 已配置；音色在可用列表内；
默认风格存在。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine

from studio.agent import exec_policy
from studio.agent.runtime import RuntimeFactory
from studio.api.deps import get_engine, get_runtime_factory, get_settings
from studio.api.profiles import key_configured
from studio.api.schemas import SettingsOut, SettingsPatch, TtsDefaultOut
from studio.config import Settings
from studio.db.repo.profiles import get_model_profile_by_id
from studio.db.repo.settings import (
    SettingsValidationError,
    SettingsValue,
    get_all_settings,
    update_settings,
    validate_settings_patch,
)
from studio.engines.tts.voice_map import DEFAULT_SPEED, DEFAULT_VOICE, voice_aliases
from studio.styles.store import style_is_usable

router = APIRouter(prefix="/api", tags=["settings"])


def _out(value: SettingsValue, env: Settings) -> SettingsOut:
    allow = (
        env.allow_unsandboxed_exec
        if value.allow_unsandboxed_exec is None
        else value.allow_unsandboxed_exec
    )
    return SettingsOut(
        stage_default_profile=value.stage_default_profile,
        web_mode=value.web_mode or env.web_mode,
        web_mode_source="ui" if value.web_mode is not None else "env",
        web_mode_env=env.web_mode,
        tts_default=TtsDefaultOut(
            voice=value.tts_voice or DEFAULT_VOICE,
            speech_rate=value.tts_speech_rate or DEFAULT_SPEED,
        ),
        default_style_preset_id=value.default_style_preset_id,
        allow_unsandboxed_exec=allow,
        allow_unsandboxed_exec_source="ui" if value.allow_unsandboxed_exec is not None else "env",
        allow_unsandboxed_exec_env=env.allow_unsandboxed_exec,
        sandbox_available=exec_policy.seatbelt_available(),
        exec_mode=exec_policy.host_exec_mode(allow),
    )


def _check_profile(engine: Engine, runtimes: RuntimeFactory, stage: str, profile_id: str) -> None:
    profile = get_model_profile_by_id(engine, profile_id)
    if profile is None:
        raise SettingsValidationError(f"{stage} 的默认模型配置不存在：{profile_id}")
    if not runtimes.has(profile.runtime):
        raise SettingsValidationError(f"模型配置 {profile.name} 的运行时未启用：{profile.runtime}")
    if not key_configured(profile):
        raise SettingsValidationError(f"模型配置 {profile.name} 的密钥未配置，不能设为默认")


def _check_references(
    engine: Engine, runtimes: RuntimeFactory, data_dir: Path, patch: dict[str, Any]
) -> None:
    for stage, profile_id in (patch.get("stage_default_profile") or {}).items():
        if profile_id is not None:
            _check_profile(engine, runtimes, stage, profile_id)
    voice = (patch.get("tts_default") or {}).get("voice")
    if voice is not None and voice not in voice_aliases():
        raise SettingsValidationError(f"音色不可用：{voice}")
    style_id = patch.get("default_style_preset_id")
    if style_id is not None and not style_is_usable(data_dir, style_id):
        raise SettingsValidationError(f"风格不存在：{style_id}")


@router.get("/settings", response_model=SettingsOut)
def get_settings_endpoint(
    engine: Engine = Depends(get_engine), env: Settings = Depends(get_settings)
) -> SettingsOut:
    return _out(get_all_settings(engine), env)


@router.patch("/settings", response_model=SettingsOut)
def patch_settings_endpoint(
    body: SettingsPatch,
    engine: Engine = Depends(get_engine),
    runtimes: RuntimeFactory = Depends(get_runtime_factory),
    env: Settings = Depends(get_settings),
) -> SettingsOut:
    patch = body.model_dump(exclude_unset=True)
    try:
        validate_settings_patch(patch)
        _check_references(engine, runtimes, env.data_dir, patch)
        return _out(update_settings(engine, patch), env)
    except SettingsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
