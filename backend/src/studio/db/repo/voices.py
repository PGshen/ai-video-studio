"""`tts_voices` 仓储：设置页可增删的 TTS 音色（计划 tts-voice-management T1）。

别名全局唯一（项目设置里只存别名）。种子由迁移 0012 写入一次，之后完全由用户增删。
删除前检查引用：被项目使用、是当前全局默认音色（没设过时回落到 `FALLBACK_DEFAULT_VOICE`），
或是最后一个音色，都不能删——静默改变已有项目的配音比一个 409 更糟。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from sqlalchemy import Engine, select

from studio.db.engine import session_scope
from studio.db.models import Project, TtsVoice
from studio.db.repo.settings import get_all_settings

FALLBACK_DEFAULT_VOICE: Final = "zizi"
"""没存过全局默认音色时用的音色；与 `voice_map.DEFAULT_VOICE` 保持一致（有测试）。"""
ENGINES: Final = ("doubao_1.0", "doubao_2.0")
GENDERS: Final = ("male", "female")
_ALIAS = re.compile(r"^[a-z0-9_]{1,40}$")
_SPEAKER_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,200}$")


@dataclass(frozen=True, slots=True)
class VoiceValue:
    """`tts_voices` 表一行的只读值对象。"""

    alias: str
    label: str
    gender: str
    speaker_id: str
    engine: str


class VoiceValidationError(ValueError):
    """字段不合法（API 映射为 422）；`errors` 逐条列出问题。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("；".join(errors))
        self.errors = errors


class VoiceNotFoundError(LookupError):
    pass


class DuplicateVoiceError(RuntimeError):
    """别名已被占用（API 映射为 409）。"""


class VoiceInUseError(RuntimeError):
    """音色不能删（API 映射为 409）：被项目使用、是默认音色，或是最后一个。"""

    def __init__(self, alias: str, project_count: int, is_default: bool, is_last: bool) -> None:
        reasons = []
        if project_count:
            reasons.append(f"被 {project_count} 个项目使用")
        if is_default:
            reasons.append("是新项目的默认音色（请先在上方改默认值）")
        if is_last:
            reasons.append("是最后一个音色")
        super().__init__(f"音色 {alias} {'，'.join(reasons)}，不能删除")
        self.project_count = project_count
        self.is_default = is_default
        self.is_last = is_last


def _to_value(row: TtsVoice) -> VoiceValue:
    return VoiceValue(
        alias=row.alias,
        label=row.label,
        gender=row.gender,
        speaker_id=row.speaker_id,
        engine=row.engine,
    )


def list_voices(engine: Engine, *, engine_version: str | None = None) -> list[VoiceValue]:
    """按创建顺序列出音色；`engine_version` 给出时只列该版本（`doubao_1.0`/`doubao_2.0`）。"""
    stmt = select(TtsVoice).order_by(TtsVoice.created_at)
    if engine_version is not None:
        stmt = stmt.where(TtsVoice.engine == engine_version)
    with session_scope(engine) as db:
        return [_to_value(row) for row in db.scalars(stmt)]


def get_voice(engine: Engine, alias: str) -> VoiceValue | None:
    with session_scope(engine) as db:
        row = db.get(TtsVoice, alias)
        return _to_value(row) if row is not None else None


def _validate(fields: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if _ALIAS.match(fields["alias"]) is None:
        errors.append("别名只允许小写字母、数字和下划线，1–40 个字符")
    if not fields["label"].strip():
        errors.append("名称不能为空")
    if _SPEAKER_ID.match(fields["speaker_id"]) is None:
        errors.append("speaker id 只允许字母、数字、下划线、点和连字符，不能为空")
    if fields["gender"] not in GENDERS:
        errors.append(f"性别必须是 {' / '.join(GENDERS)}")
    if fields["engine"] not in ENGINES:
        errors.append(f"版本必须是 {' / '.join(ENGINES)}")
    return errors


def create_voice(
    engine: Engine, *, alias: str, label: str, gender: str, speaker_id: str, engine_version: str
) -> VoiceValue:
    """新增音色；不合法抛 `VoiceValidationError`（一次列出全部问题），别名重复抛
    `DuplicateVoiceError`。"""
    fields = {
        "alias": alias,
        "label": label,
        "gender": gender,
        "speaker_id": speaker_id,
        "engine": engine_version,
    }
    errors = _validate(fields)
    if errors:
        raise VoiceValidationError(errors)
    with session_scope(engine) as db:
        if db.get(TtsVoice, alias) is not None:
            raise DuplicateVoiceError(f"已有同名的音色别名：{alias}")
        row = TtsVoice(**{**fields, "label": label.strip()})
        db.add(row)
        db.flush()
        return _to_value(row)


def delete_voice(engine: Engine, alias: str) -> None:
    """删除音色。被项目使用、是默认音色或是最后一个时抛 `VoiceInUseError`，不删。"""
    default = get_all_settings(engine).tts_voice or FALLBACK_DEFAULT_VOICE
    with session_scope(engine) as db:
        row = db.get(TtsVoice, alias)
        if row is None:
            raise VoiceNotFoundError(alias)
        used = sum(
            1 for settings in db.scalars(select(Project.settings)) if settings.get("voice") == alias
        )
        is_default = alias == default
        is_last = len(db.scalars(select(TtsVoice.alias).limit(2)).all()) < 2
        if used or is_default or is_last:
            raise VoiceInUseError(alias, used, is_default, is_last)
        db.delete(row)
