"""`tts_voices` 仓储（计划 tts-voice-management T1）：种子、新增、删除与引用检查。"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, inspect

from studio.db.repo.projects import create_project
from studio.db.repo.settings import update_settings
from studio.db.repo.voices import (
    DuplicateVoiceError,
    VoiceInUseError,
    VoiceNotFoundError,
    VoiceValidationError,
    create_voice,
    delete_voice,
    get_voice,
    list_voices,
)

SEED_ALIASES = ["sisi", "xiaozhupeiqi", "xiaoxinjiejie", "zizi", "yunzhou", "xiaohe"]


def _new(alias: str = "newone", version: str = "doubao_2.0", **over: object) -> dict[str, object]:
    return {
        "alias": alias,
        "label": "新音色",
        "gender": "female",
        "speaker_id": "zh_female_new_uranus_bigtts",
        "engine_version": version,
        **over,
    }


def test_migration_seeds_the_six_known_voices(migrated_engine: Engine) -> None:
    voices = list_voices(migrated_engine)

    assert sorted(v.alias for v in voices) == sorted(SEED_ALIASES)
    zizi = get_voice(migrated_engine, "zizi")
    assert zizi is not None
    assert zizi.label == "清澈梓梓"
    assert zizi.speaker_id == "zh_female_qingchezizi_uranus_bigtts"
    assert zizi.engine == "doubao_2.0"
    sisi = get_voice(migrated_engine, "sisi")
    assert sisi is not None and sisi.engine == "doubao_1.0"
    assert sisi.speaker_id == "zh_female_shuangkuaisisi_moon_bigtts"
    assert "tts_voices" in inspect(migrated_engine).get_table_names()


def test_list_filters_by_engine_and_keeps_creation_order(migrated_engine: Engine) -> None:
    assert [v.alias for v in list_voices(migrated_engine, engine_version="doubao_1.0")] == ["sisi"]
    assert [v.alias for v in list_voices(migrated_engine)] == SEED_ALIASES
    create_voice(migrated_engine, **_new())  # type: ignore[arg-type]
    assert list_voices(migrated_engine)[-1].alias == "newone"


def test_create_round_trips_for_both_versions(migrated_engine: Engine) -> None:
    v1 = create_voice(migrated_engine, **_new("old_one", "doubao_1.0"))  # type: ignore[arg-type]
    v2 = create_voice(migrated_engine, **_new("new_one", "doubao_2.0"))  # type: ignore[arg-type]

    assert (v1.engine, v2.engine) == ("doubao_1.0", "doubao_2.0")
    assert get_voice(migrated_engine, "old_one") == v1


def test_create_rejects_duplicate_alias(migrated_engine: Engine) -> None:
    with pytest.raises(DuplicateVoiceError):
        create_voice(migrated_engine, **_new("zizi"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "over",
    [
        {"alias": "Bad Alias"},
        {"alias": ""},
        {"alias": "a" * 41},
        {"alias": "中文"},
        {"label": "  "},
        {"speaker_id": ""},
        {"speaker_id": "has space"},
        {"gender": "other"},
        {"engine_version": "doubao_3.0"},
    ],
)
def test_create_validates_fields(migrated_engine: Engine, over: dict[str, object]) -> None:
    with pytest.raises(VoiceValidationError):
        create_voice(migrated_engine, **_new(**over))  # type: ignore[arg-type]
    assert len(list_voices(migrated_engine)) == len(SEED_ALIASES)


def test_validation_lists_every_problem(migrated_engine: Engine) -> None:
    with pytest.raises(VoiceValidationError) as info:
        create_voice(migrated_engine, **_new("BAD", gender="x", engine_version="y"))  # type: ignore[arg-type]
    assert len(info.value.errors) == 3


def test_delete_removes_an_unused_voice(migrated_engine: Engine) -> None:
    delete_voice(migrated_engine, "xiaohe")

    assert get_voice(migrated_engine, "xiaohe") is None


def test_delete_unknown_voice(migrated_engine: Engine) -> None:
    with pytest.raises(VoiceNotFoundError):
        delete_voice(migrated_engine, "nope")


def test_delete_refuses_a_voice_used_by_projects(migrated_engine: Engine) -> None:
    create_project(migrated_engine, title="a", settings={"voice": "yunzhou"})
    create_project(migrated_engine, title="b", settings={"voice": "yunzhou"})
    create_project(migrated_engine, title="c", settings={"voice": "xiaohe"})

    with pytest.raises(VoiceInUseError) as info:
        delete_voice(migrated_engine, "yunzhou")

    assert info.value.project_count == 2
    assert not info.value.is_default
    assert "2" in str(info.value)
    assert get_voice(migrated_engine, "yunzhou") is not None


def test_delete_refuses_the_global_default(migrated_engine: Engine) -> None:
    update_settings(migrated_engine, {"tts_default": {"voice": "xiaohe"}})

    with pytest.raises(VoiceInUseError) as info:
        delete_voice(migrated_engine, "xiaohe")

    assert info.value.is_default


def test_delete_refuses_the_built_in_fallback_default(migrated_engine: Engine) -> None:
    """Nothing stored: the effective default is `zizi` (voice_map.DEFAULT_VOICE)."""
    with pytest.raises(VoiceInUseError) as info:
        delete_voice(migrated_engine, "zizi")

    assert info.value.is_default


def test_delete_refuses_the_last_voice(migrated_engine: Engine) -> None:
    update_settings(migrated_engine, {"tts_default": {"voice": "sisi"}})
    for alias in SEED_ALIASES:
        if alias != "sisi":
            delete_voice(migrated_engine, alias)

    with pytest.raises(VoiceInUseError):
        delete_voice(migrated_engine, "sisi")


def test_deleted_seed_does_not_come_back_on_migrate(migrated_engine: Engine) -> None:
    from studio.db.engine import migrate

    delete_voice(migrated_engine, "xiaohe")
    migrate(migrated_engine)

    assert get_voice(migrated_engine, "xiaohe") is None


def test_fallback_default_matches_the_engine_constant() -> None:
    from studio.db.repo.voices import FALLBACK_DEFAULT_VOICE
    from studio.engines.tts.voice_map import DEFAULT_VOICE

    assert FALLBACK_DEFAULT_VOICE == DEFAULT_VOICE
