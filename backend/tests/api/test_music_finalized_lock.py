"""Once `concept` is finalized the song and its lyrics are frozen (TD-81): the upload-song,
upload-lyrics and delete-lyrics endpoints answer 409 and leave the workspace untouched."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from engines.audio_fixtures import SAMPLE_RATE
from fixtures.audio_engine import write_wav
from fixtures.import_music import write_click_song
from fixtures.import_music.seed import seed_mv_project
from studio.db.repo.stages import get_stage, update_stage
from studio.timeline.lyrics import LYRICS_PATH

from .conftest import ApiEnv, assert_detail

LRC = "[00:02.00]第一句\n[00:06.00]第二句\n"
OLD_LRC = "[00:01.00]旧的\n"


def _mv(api_env: ApiEnv) -> tuple[str, Path]:
    pid = seed_mv_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    workdir = api_env.workdir(pid)
    (workdir / "music").mkdir(exist_ok=True)
    write_click_song(workdir / "music" / "source.wav")
    (workdir / LYRICS_PATH).write_text(OLD_LRC, encoding="utf-8")
    return pid, workdir


def _finalize_concept(api_env: ApiEnv, pid: str) -> None:
    update_stage(api_env.app.state.engine, pid, "concept", status="finalized")


def _snapshot(workdir: Path) -> dict[str, bytes]:
    return {
        path.relative_to(workdir).as_posix(): path.read_bytes()
        for path in sorted(workdir.rglob("*"))
        if path.is_file()
    }


def _new_song(tmp_path: Path) -> bytes:
    return write_wav(
        tmp_path / "new.wav", np.zeros(int(SAMPLE_RATE * 8.0)), SAMPLE_RATE
    ).read_bytes()


async def _upload_song(api_env: ApiEnv, pid: str, data: bytes):
    return await api_env.client.post(
        f"/api/projects/{pid}/music/source", files={"file": ("新歌.wav", data, "audio/wav")}
    )


async def _upload_lyrics(api_env: ApiEnv, pid: str):
    return await api_env.client.post(
        f"/api/projects/{pid}/music/lyrics",
        files={"file": ("歌词.lrc", LRC.encode(), "application/octet-stream")},
    )


async def _delete_lyrics(api_env: ApiEnv, pid: str):
    return await api_env.client.delete(f"/api/projects/{pid}/music/lyrics")


async def test_the_seeded_concept_starts_active(api_env: ApiEnv) -> None:
    pid, _ = _mv(api_env)
    stage = get_stage(api_env.app.state.engine, pid, "concept")
    assert stage is not None and stage.status == "active"


async def test_a_new_song_is_refused_after_concept_is_finalized(
    api_env: ApiEnv, tmp_path: Path
) -> None:
    pid, workdir = _mv(api_env)
    _finalize_concept(api_env, pid)
    before = _snapshot(workdir)
    response = await _upload_song(api_env, pid, _new_song(tmp_path))
    assert response.status_code == 409
    detail = assert_detail(response)
    assert "已定稿" in detail and "重新打开" in detail and "歌曲" in detail
    assert _snapshot(workdir) == before
    assert not (workdir / ".cache").exists()  # not even a scratch directory
    assert pid not in api_env.app.state.music_uploads


async def test_lyrics_cannot_be_uploaded_or_deleted_after_concept_is_finalized(
    api_env: ApiEnv,
) -> None:
    pid, workdir = _mv(api_env)
    _finalize_concept(api_env, pid)
    before = _snapshot(workdir)
    for response in (await _upload_lyrics(api_env, pid), await _delete_lyrics(api_env, pid)):
        assert response.status_code == 409
        detail = assert_detail(response)
        assert "已定稿" in detail and "重新打开" in detail and "歌词" in detail
    assert _snapshot(workdir) == before
    assert (workdir / LYRICS_PATH).read_text(encoding="utf-8") == OLD_LRC
    assert not (workdir / ".cache").exists()
    assert pid not in api_env.app.state.music_uploads


async def test_all_three_work_while_concept_is_active(api_env: ApiEnv, tmp_path: Path) -> None:
    pid, workdir = _mv(api_env)
    new = _new_song(tmp_path)
    assert (await _upload_song(api_env, pid, new)).status_code == 200
    assert (workdir / "music" / "source.wav").read_bytes() == new
    assert (await _upload_lyrics(api_env, pid)).status_code == 200
    assert (workdir / LYRICS_PATH).read_text(encoding="utf-8") == LRC
    assert (await _delete_lyrics(api_env, pid)).status_code == 204
    assert not (workdir / LYRICS_PATH).exists()


async def test_reopening_concept_unlocks_the_song_again(api_env: ApiEnv) -> None:
    pid, _ = _mv(api_env)
    _finalize_concept(api_env, pid)
    assert (await _delete_lyrics(api_env, pid)).status_code == 409
    update_stage(api_env.app.state.engine, pid, "concept", status="active")
    assert (await _delete_lyrics(api_env, pid)).status_code == 204
