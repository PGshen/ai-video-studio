"""TTS 引擎工厂（计划 M3 T1；tts-voice-management T2）。

不迁移旧项目的 `factory.py`：它依赖已废弃的 `TTSEngineConfig` 表。真实 key 按固定环境变量名
读取（不进 `Settings`），原则同 `model_profiles.api_key_env`——真实 key 不落进配置字段，见
`config.py` 的既有说明。音色（可在设置页增删，存在 `tts_voices` 表）由调用方查库后传入，
引擎层不依赖数据库。
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Protocol

from studio.engines.tts.base import TTSVoiceSpec
from studio.engines.tts.volcengine import VolcengineTTSEngine

VOLCENGINE_TTS_API_KEY_ENV = "VOLCENGINE_TTS_API_KEY"


class VoiceLike(Protocol):
    """`db.repo.voices.VoiceValue` 满足这个形状；引擎层只认这三个字段。"""

    @property
    def alias(self) -> str: ...
    @property
    def speaker_id(self) -> str: ...
    @property
    def engine(self) -> str: ...


def build_tts_engine(voices: Iterable[VoiceLike]) -> VolcengineTTSEngine:
    """按环境变量里的真实 key 和给定音色建一个 `VolcengineTTSEngine`。

    语速不在构造时绑定——`TTSEngine.synthesize` 按 `TTSRequest` 逐次传入。每个音色带自己的
    豆包版本（v1/v2），同一个引擎实例可以混用。
    """
    api_key = os.environ.get(VOLCENGINE_TTS_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            f"环境变量 {VOLCENGINE_TTS_API_KEY_ENV} 未设置，请在 backend/.env 中配置。"
        )
    return VolcengineTTSEngine(
        api_key=api_key,
        voices={v.alias: TTSVoiceSpec(speaker_id=v.speaker_id, engine=v.engine) for v in voices},
    )
