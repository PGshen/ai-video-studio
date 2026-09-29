"""TTS 引擎工厂（计划 M3 T1）。

不迁移旧项目的 `factory.py`：它依赖已废弃的 `TTSEngineConfig`/`TTSVoice`
表。真实 key 按固定环境变量名读取（不进 `Settings`），原则同
`model_profiles.api_key_env`——真实 key 不落进配置字段，见 `config.py`
的既有说明。
"""

from __future__ import annotations

import os

from studio.engines.tts.volcengine import VolcengineTTSEngine

VOLCENGINE_TTS_API_KEY_ENV = "VOLCENGINE_TTS_API_KEY"


def build_tts_engine() -> VolcengineTTSEngine:
    """按环境变量里的真实 key 建一个 `VolcengineTTSEngine`。

    音色/语速不在构造时绑定——`TTSEngine.synthesize` 按 `TTSRequest`
    逐次传入，调用方（`synthesize_tts` 工具）从 `project.settings` 读到
    这两个值后直接放进 `TTSRequest`；固定单一引擎版本 `doubao_2.0`/
    `seed-tts-2.0`，不做可配置。
    """
    api_key = os.environ.get(VOLCENGINE_TTS_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            f"环境变量 {VOLCENGINE_TTS_API_KEY_ENV} 未设置，请在 backend/.env 中配置。"
        )
    return VolcengineTTSEngine(api_key=api_key, resource_id="seed-tts-2.0", engine="doubao_2.0")
