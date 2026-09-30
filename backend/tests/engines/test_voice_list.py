"""音色列表（计划 M5 T8）：别名 → 中文名、性别。

标签来自旧项目 dev DB 的 `tts_voices` 表（2026-09-30 只读查证，`speaker_id` 与
`voice_map.py` 一一对应），不是凭记忆写的。
"""

from __future__ import annotations

import pytest

from studio.engines.tts.voice_map import (
    DEFAULT_ENGINE,
    DEFAULT_VOICE,
    VOICE_MAP_BY_ENGINE,
    VoiceInfo,
    list_voices,
    voice_aliases,
)


def test_every_supported_voice_is_listed_with_a_label_and_gender() -> None:
    voices = list_voices()

    assert [v.alias for v in voices] == voice_aliases()
    for voice in voices:
        assert voice.label.strip()
        assert voice.gender in ("male", "female")
        assert voice.engine == DEFAULT_ENGINE


def test_labels_match_the_legacy_voice_table() -> None:
    by_alias = {v.alias: v for v in list_voices()}

    assert by_alias["zizi"] == VoiceInfo("zizi", "清澈梓梓", "female", DEFAULT_ENGINE)
    assert by_alias["xiaohe"].label == "小禾"
    assert by_alias["xiaoxinjiejie"].label == "小新小姐姐"
    assert by_alias["xiaozhupeiqi"].label == "小猪佩奇"
    assert (by_alias["yunzhou"].label, by_alias["yunzhou"].gender) == ("云舟", "male")


def test_default_voice_is_one_of_the_listed_voices() -> None:
    assert DEFAULT_VOICE in voice_aliases()


def test_every_engine_voice_has_metadata() -> None:
    """新增音色别名时必须同时补标签，否则设置页会出现没有名字的音色。"""
    for engine, aliases in VOICE_MAP_BY_ENGINE.items():
        assert [v.alias for v in list_voices(engine)] == list(aliases)


def test_unknown_engine_is_an_error() -> None:
    with pytest.raises(ValueError):
        list_voices("nope")
