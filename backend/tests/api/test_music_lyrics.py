"""`POST/DELETE /api/projects/{id}/music/lyrics` and the lyrics in `music/meta` (mv-lyrics T3)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fixtures.import_music import write_click_song
from fixtures.import_music.seed import seed_mv_project
from fixtures.synth_music.seed import seed_reel_project
from studio.timeline.lyrics import LYRICS_PATH, MAX_LRC_BYTES

from .conftest import ApiEnv, assert_detail

LRC = "[00:02.00]第一句\n[00:06.00]第二句\n[00:10.00]第三句\n"  # the song is 20 s long


def _mv(api_env: ApiEnv, *, song: bool = True) -> tuple[str, Path]:
    pid = seed_mv_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    workdir = api_env.workdir(pid)
    if song:
        (workdir / "music").mkdir(exist_ok=True)
        write_click_song(workdir / "music" / "source.wav")
    return pid, workdir


def _url(pid: str) -> str:
    return f"/api/projects/{pid}/music/lyrics"


async def _upload(api_env: ApiEnv, pid: str, data: bytes | str, field: str = "file"):
    raw = data.encode() if isinstance(data, str) else data
    return await api_env.client.post(
        _url(pid), files={field: ("歌词.lrc", raw, "application/octet-stream")}
    )


def _residue(workdir: Path) -> list[str]:
    tmp = workdir / ".cache" / "tmp"
    found = [p.name for p in tmp.iterdir()] if tmp.is_dir() else []
    return found + [p.name for p in (workdir / "music").iterdir() if p.name.startswith(".")]


async def test_upload_stores_the_lyrics_and_reports_them(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    response = await _upload(api_env, pid, "﻿" + LRC)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lines"] == 3
    stored = (workdir / LYRICS_PATH).read_bytes()
    assert stored == LRC.encode()  # BOM dropped, content kept
    assert body["sha256"] == hashlib.sha256(stored).hexdigest()
    assert _residue(workdir) == []


async def test_a_second_upload_replaces_the_first(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    assert (await _upload(api_env, pid, LRC)).status_code == 200
    assert (await _upload(api_env, pid, "[00:01.00]新的")).status_code == 200
    assert (workdir / LYRICS_PATH).read_text("utf-8") == "[00:01.00]新的"


async def test_lyrics_need_the_song_first(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env, song=False)
    response = await _upload(api_env, pid, LRC)
    assert response.status_code == 422 and "先上传歌曲" in assert_detail(response)
    assert not (workdir / LYRICS_PATH).exists()


async def test_bad_files_are_422_and_the_old_lyrics_survive(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    assert (await _upload(api_env, pid, LRC)).status_code == 200
    cases = [
        (b"\xff\xfe\x00bad", "UTF-8"),
        ("只有文字\n没有时间戳", "时间戳"),
        ("[00:01.00]a\n[09:00.00]b", "晚于歌曲"),
        ("[00:01.00]" + "词" * MAX_LRC_BYTES, "200 KB"),
        ("", "没有收到文件"),
    ]
    for data, needle in cases:
        response = await _upload(api_env, pid, data)
        assert response.status_code == 422, data
        assert needle in assert_detail(response), (needle, response.text)
        assert (workdir / LYRICS_PATH).read_bytes() == LRC.encode()
    assert _residue(workdir) == []


async def test_the_field_must_be_called_file(api_env: ApiEnv) -> None:
    pid, _ = _mv(api_env)
    response = await _upload(api_env, pid, LRC, field="lyrics")
    assert response.status_code == 422 and "file" in assert_detail(response)


async def test_unknown_and_synth_projects_are_404(api_env: ApiEnv) -> None:
    assert (await _upload(api_env, "nope", LRC)).status_code == 404
    pid = seed_reel_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    response = await _upload(api_env, pid, LRC)
    assert response.status_code == 404 and "导入音乐" in assert_detail(response)


async def test_busy_and_concurrent_uploads_are_409(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    turn = await api_env.make_busy(pid, stage="concept")
    try:
        assert (await _upload(api_env, pid, LRC)).status_code == 409
    finally:
        await api_env.release_busy(turn)
    api_env.app.state.music_uploads.add(pid)
    assert (await _upload(api_env, pid, LRC)).status_code == 409
    assert not (workdir / LYRICS_PATH).exists()


async def test_delete_removes_the_lyrics_and_is_idempotent(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    assert (await _upload(api_env, pid, LRC)).status_code == 200
    assert (await api_env.client.delete(_url(pid))).status_code == 204
    assert not (workdir / LYRICS_PATH).exists()
    assert (await api_env.client.delete(_url(pid))).status_code == 204


async def test_delete_respects_busy_and_project_kind(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    assert (await _upload(api_env, pid, LRC)).status_code == 200
    turn = await api_env.make_busy(pid, stage="concept")
    try:
        assert (await api_env.client.delete(_url(pid))).status_code == 409
    finally:
        await api_env.release_busy(turn)
    assert (workdir / LYRICS_PATH).exists()
    reel = seed_reel_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    assert (await api_env.client.delete(_url(reel))).status_code == 404


async def test_meta_lists_the_lyrics_in_song_seconds(api_env: ApiEnv) -> None:
    pid, _ = _mv(api_env)
    meta = (await api_env.client.get(f"/api/projects/{pid}/music/meta")).json()
    assert meta["lyrics"] == []
    assert (await _upload(api_env, pid, LRC)).status_code == 200
    meta = (await api_env.client.get(f"/api/projects/{pid}/music/meta")).json()
    assert [(x["text"], x["start"], x["end"]) for x in meta["lyrics"]] == [
        ("第一句", 2.0, 6.0),
        ("第二句", 6.0, 10.0),
        ("第三句", 10.0, 15.0),
    ]


async def test_a_hand_broken_lyrics_file_gives_empty_lyrics_in_meta(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    (workdir / LYRICS_PATH).write_text("没有时间戳", encoding="utf-8")
    meta = (await api_env.client.get(f"/api/projects/{pid}/music/meta")).json()
    assert meta["lyrics"] == []
