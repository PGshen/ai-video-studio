"""音色别名 → 供应商 speaker id 的静态映射（计划 M3 T1）。

迁移自 `../ai-video/backend/app/engines/tts/voice_map.py`，内容不变。
"""

from __future__ import annotations

DEFAULT_ENGINE = "doubao_2.0"
"""项目固定使用的引擎版本（见 `factory.build_tts_engine`）。"""
DEFAULT_VOICE = "zizi"
DEFAULT_SPEED = 1.0

VOICE_MAP_BY_ENGINE: dict[str, dict[str, str]] = {
    "doubao_1.0": {
        "sisi": "zh_female_shuangkuaisisi_moon_bigtts",
    },
    "doubao_2.0": {
        "xiaozhupeiqi": "zh_female_peiqi_uranus_bigtts",
        "xiaoxinjiejie": "zh_female_chunribu_uranus_bigtts",
        "zizi": "zh_female_qingchezizi_uranus_bigtts",
        "yunzhou": "zh_male_m191_uranus_bigtts",
        "xiaohe": "zh_female_xiaohe_uranus_bigtts",
    },
}


def resolve_speaker(alias: str, engine: str) -> str:
    """把别名换算成指定引擎下的供应商 speaker id；别名或引擎不存在时报错。"""
    voices = VOICE_MAP_BY_ENGINE.get(engine)
    if voices is None:
        raise ValueError(f"Unsupported TTS engine: {engine}")
    try:
        return voices[alias]
    except KeyError as exc:
        raise ValueError(f"Voice {alias!r} is not available for {engine}") from exc


def voice_aliases(engine: str = DEFAULT_ENGINE) -> list[str]:
    """指定引擎下可用的音色别名（按映射表顺序）；引擎不存在时报错。"""
    voices = VOICE_MAP_BY_ENGINE.get(engine)
    if voices is None:
        raise ValueError(f"Unsupported TTS engine: {engine}")
    return list(voices)
