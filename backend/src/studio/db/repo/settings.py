"""`settings` 仓储：键值配置的带类型读写（设计 §3.1、计划 M5 T1）。

键固定，未知键拒绝：

- `stage_default_profile`：`{阶段: 模型配置 id}`，新建会话时预选。
- `web_mode`：`tools`/`native`；缺省表示跟随环境变量 `STUDIO_WEB_MODE`（`effective_web_mode`）。
- `tts_default`：`{voice, speech_rate}`，创建项目时复制进 `project.settings`（决策 D5）。
- `default_style_preset_id`：创建项目时不指定风格就用它。

只校验「形状」：引用其他表的检查（模型配置、风格预设是否存在、key 是否已配置）在 api 层做，
避免 `db.repo` 内部互相依赖。`update_settings` 是补丁语义：顶层键只改出现的；
`stage_default_profile` 按阶段合并、`tts_default` 按字段合并；值为 `None` 表示清除，
清空后对应的行会被删掉。整个补丁先校验、再在同一个事务里写入，要么全成要么全不成。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sqlalchemy import Engine, select

from studio.db.engine import session_scope
from studio.db.models import Setting

STAGES: Final = ("brainstorm", "topic", "narrative", "animation", "animation_html", "style")
WEB_MODES: Final = ("tools", "native")
SPEECH_RATE_MIN: Final = 0.5
SPEECH_RATE_MAX: Final = 2.0
"""火山引擎以 -50 至 100 的相对值表示语速（`engines/tts/volcengine.py`），项目倍速 1.0 对应 0，
所以倍速范围是 0.5–2.0。"""

_KEY_STAGE_DEFAULT_PROFILE: Final = "stage_default_profile"
_KEY_WEB_MODE: Final = "web_mode"
_KEY_TTS_DEFAULT: Final = "tts_default"
_KEY_DEFAULT_STYLE: Final = "default_style_preset_id"
_TTS_FIELDS: Final = ("voice", "speech_rate")


class SettingsValidationError(ValueError):
    """补丁里有不合法的键或值（API 映射为 422）。"""


@dataclass(frozen=True, slots=True)
class SettingsValue:
    """所有配置的只读快照；没设置的项是空值，由调用方决定回落到什么。"""

    stage_default_profile: dict[str, str] = field(default_factory=dict)
    web_mode: Literal["tools", "native"] | None = None
    tts_voice: str | None = None
    tts_speech_rate: float | None = None
    default_style_preset_id: str | None = None


def _non_empty_str(value: object, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SettingsValidationError(f"{what} 必须是非空字符串")
    return value


def _validate_stage_defaults(patch: object) -> dict[str, str | None]:
    if not isinstance(patch, Mapping):
        raise SettingsValidationError("stage_default_profile 必须是 {阶段: 模型配置 id} 对象")
    result: dict[str, str | None] = {}
    for stage, profile_id in patch.items():
        if stage not in STAGES:
            raise SettingsValidationError(f"未知阶段：{stage}")
        if profile_id is None:
            result[stage] = None
        else:
            result[stage] = _non_empty_str(profile_id, f"{stage} 的默认模型")
    return result


def _validate_web_mode(value: object) -> str | None:
    if value is None:
        return None
    if value not in WEB_MODES:
        raise SettingsValidationError(f"web_mode 只接受 {' / '.join(WEB_MODES)}")
    return str(value)


def _validate_tts_default(patch: object) -> dict[str, Any]:
    if not isinstance(patch, Mapping):
        raise SettingsValidationError("tts_default 必须是 {voice, speech_rate} 对象")
    result: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in _TTS_FIELDS:
            raise SettingsValidationError(f"tts_default 不支持字段：{key}")
        if value is None:
            result[key] = None
        elif key == "voice":
            result[key] = _non_empty_str(value, "音色")
        else:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise SettingsValidationError("语速必须是数字")
            if not SPEECH_RATE_MIN <= value <= SPEECH_RATE_MAX:
                raise SettingsValidationError(
                    f"语速必须在 {SPEECH_RATE_MIN}–{SPEECH_RATE_MAX} 之间"
                )
            result[key] = float(value)
    return result


def _validate(patch: Mapping[str, Any]) -> dict[str, Any]:
    known = {
        _KEY_STAGE_DEFAULT_PROFILE: _validate_stage_defaults,
        _KEY_WEB_MODE: _validate_web_mode,
        _KEY_TTS_DEFAULT: _validate_tts_default,
        _KEY_DEFAULT_STYLE: lambda v: (
            None if v is None else _non_empty_str(v, "default_style_preset_id")
        ),
    }
    checked: dict[str, Any] = {}
    for key, value in patch.items():
        validator = known.get(key)
        if validator is None:
            raise SettingsValidationError(f"未知配置项：{key}")
        checked[key] = validator(value)
    return checked


def _merge(current: Mapping[str, Any] | None, patch: Mapping[str, Any]) -> dict[str, Any] | None:
    merged = {**(current or {}), **patch}
    merged = {k: v for k, v in merged.items() if v is not None}
    return merged or None


def validate_settings_patch(patch: Mapping[str, Any]) -> None:
    """只做形状校验，不写库；不合法时抛 `SettingsValidationError`。"""
    _validate(patch)


def update_settings(engine: Engine, patch: Mapping[str, Any]) -> SettingsValue:
    """应用补丁并返回更新后的全部配置；不合法时抛 `SettingsValidationError`，什么都不写。"""
    checked = _validate(patch)
    with session_scope(engine) as db:
        rows = {row.key: row for row in db.scalars(select(Setting))}
        for key, value in checked.items():
            if key in (_KEY_STAGE_DEFAULT_PROFILE, _KEY_TTS_DEFAULT):
                row = rows.get(key)
                value = _merge(row.value if row is not None else None, value)
            row = rows.get(key)
            if value is None:
                if row is not None:
                    db.delete(row)
            elif row is None:
                db.add(Setting(key=key, value=value))
            else:
                row.value = value
    return get_all_settings(engine)


def get_all_settings(engine: Engine) -> SettingsValue:
    """读取全部配置；没存过的项是空值。"""
    with session_scope(engine) as db:
        stored = {row.key: row.value for row in db.scalars(select(Setting))}
    tts = stored.get(_KEY_TTS_DEFAULT) or {}
    return SettingsValue(
        stage_default_profile=dict(stored.get(_KEY_STAGE_DEFAULT_PROFILE) or {}),
        web_mode=stored.get(_KEY_WEB_MODE),
        tts_voice=tts.get("voice"),
        tts_speech_rate=tts.get("speech_rate"),
        default_style_preset_id=stored.get(_KEY_DEFAULT_STYLE),
    )


def web_mode_override(engine: Engine) -> Literal["tools", "native"] | None:
    """界面设置的联网模式；`None` 表示没有覆盖，跟随环境变量。"""
    return get_all_settings(engine).web_mode


def effective_web_mode(
    engine: Engine, env_default: Literal["tools", "native"]
) -> Literal["tools", "native"]:
    """界面覆盖优先，否则用环境变量（`Settings.web_mode`）。TurnRunner 每轮读一次，不缓存。"""
    return web_mode_override(engine) or env_default
