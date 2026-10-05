"""`POST /api/projects/{id}/music/source` (4B T1): validation order, atomic write, no residue."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest

from engines.audio_fixtures import SAMPLE_RATE
from fixtures.audio_engine import write_wav
from fixtures.import_music.seed import seed_mv_project
from fixtures.synth_music.seed import seed_reel_project
from studio.api import music_import

from .conftest import ApiEnv, assert_detail


def _wav_bytes(tmp_path: Path, seconds: float = 8.0, name: str = "src.wav") -> bytes:
    return write_wav(
        tmp_path / name, np.zeros(int(SAMPLE_RATE * seconds)), SAMPLE_RATE
    ).read_bytes()


def _mp3_bytes(tmp_path: Path, seconds: float = 8.0) -> bytes:
    wav = write_wav(tmp_path / "m.wav", np.zeros(int(SAMPLE_RATE * seconds)), SAMPLE_RATE)
    out = tmp_path / "m.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), str(out)], check=True)
    return out.read_bytes()


def _mv(api_env: ApiEnv) -> tuple[str, Path]:
    pid = seed_mv_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    return pid, api_env.workdir(pid)


def _url(pid: str) -> str:
    return f"/api/projects/{pid}/music/source"


async def _upload(api_env: ApiEnv, pid: str, name: str, data: bytes):
    return await api_env.client.post(
        _url(pid), files={"file": (name, data, "application/octet-stream")}
    )


def _residue(workdir: Path) -> list[str]:
    tmp = workdir / ".cache" / "tmp"
    found = [p.name for p in tmp.iterdir()] if tmp.is_dir() else []
    music = workdir / "music"
    found += (
        [p.name for p in music.iterdir() if not p.name.startswith("source.")]
        if music.is_dir()
        else []
    )
    return found


async def test_upload_writes_source_and_reports_it(api_env: ApiEnv, tmp_path: Path) -> None:
    pid, workdir = _mv(api_env)
    data = _wav_bytes(tmp_path)
    response = await _upload(api_env, pid, "我的 歌.WAV", data)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"] == "source.wav" and body["size"] == len(data)
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert body["duration"] == pytest.approx(8.0, abs=0.05)
    assert (workdir / "music" / "source.wav").read_bytes() == data
    assert _residue(workdir) == []


async def test_new_song_replaces_the_old_source(api_env: ApiEnv, tmp_path: Path) -> None:
    pid, workdir = _mv(api_env)
    assert (await _upload(api_env, pid, "a.mp3", _mp3_bytes(tmp_path))).status_code == 200
    assert (await _upload(api_env, pid, "b.wav", _wav_bytes(tmp_path))).status_code == 200
    assert sorted(p.name for p in (workdir / "music").iterdir()) == ["source.wav"]


async def test_old_analysis_is_kept_when_the_song_changes(api_env: ApiEnv, tmp_path: Path) -> None:
    pid, workdir = _mv(api_env)
    (workdir / "music").mkdir()
    (workdir / "music" / "analysis.json").write_text("{}")
    (workdir / "music" / "sections.json").write_text("{}")
    assert (await _upload(api_env, pid, "a.wav", _wav_bytes(tmp_path))).status_code == 200
    assert (workdir / "music" / "analysis.json").exists()
    assert (workdir / "music" / "sections.json").exists()


async def test_unknown_project_is_404(api_env: ApiEnv, tmp_path: Path) -> None:
    response = await _upload(api_env, "nope", "a.wav", _wav_bytes(tmp_path))
    assert response.status_code == 404


async def test_synth_project_is_404(api_env: ApiEnv, tmp_path: Path) -> None:
    pid = seed_reel_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    response = await _upload(api_env, pid, "a.wav", _wav_bytes(tmp_path))
    assert response.status_code == 404
    assert "导入音乐" in assert_detail(response)


async def test_busy_project_is_409(api_env: ApiEnv, tmp_path: Path) -> None:
    pid, workdir = _mv(api_env)
    turn = await api_env.make_busy(pid, stage="concept")
    try:
        response = await _upload(api_env, pid, "a.wav", _wav_bytes(tmp_path))
    finally:
        await api_env.release_busy(turn)
    assert response.status_code == 409
    assert not (workdir / "music" / "source.wav").exists()


async def test_concurrent_upload_on_same_project_is_409(api_env: ApiEnv, tmp_path: Path) -> None:
    pid, _ = _mv(api_env)
    api_env.app.state.music_uploads.add(pid)
    response = await _upload(api_env, pid, "a.wav", _wav_bytes(tmp_path))
    assert response.status_code == 409


@pytest.mark.parametrize("name", ["a.txt", "a.mp4", "noext", "a.mp3.exe"])
async def test_extension_must_be_whitelisted(api_env: ApiEnv, tmp_path: Path, name: str) -> None:
    pid, workdir = _mv(api_env)
    response = await _upload(api_env, pid, name, _wav_bytes(tmp_path))
    assert response.status_code == 422
    assert not (workdir / "music").exists() or _residue(workdir) == []


async def test_text_posing_as_mp3_is_422_and_old_source_survives(
    api_env: ApiEnv, tmp_path: Path
) -> None:
    pid, workdir = _mv(api_env)
    good = _wav_bytes(tmp_path)
    assert (await _upload(api_env, pid, "a.wav", good)).status_code == 200
    response = await _upload(api_env, pid, "a.mp3", b"definitely not audio")
    assert response.status_code == 422 and "音频" in assert_detail(response)
    assert (workdir / "music" / "source.wav").read_bytes() == good
    assert _residue(workdir) == []


async def test_zero_byte_file_is_422(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    response = await _upload(api_env, pid, "a.wav", b"")
    assert response.status_code == 422
    assert _residue(workdir) == []


@pytest.mark.parametrize("seconds", [2.0, 601.0])
async def test_duration_outside_5_to_600_is_422(
    api_env: ApiEnv, tmp_path: Path, seconds: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, workdir = _mv(api_env)
    monkeypatch.setattr(music_import, "MAX_UPLOAD_BYTES", 10**9)
    response = await _upload(api_env, pid, "a.wav", _wav_bytes(tmp_path, seconds))
    assert response.status_code == 422 and "时长" in assert_detail(response)
    assert _residue(workdir) == []


async def test_size_limit_is_inclusive(
    api_env: ApiEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, workdir = _mv(api_env)
    data = _wav_bytes(tmp_path)
    monkeypatch.setattr(music_import, "MAX_UPLOAD_BYTES", len(data) - 1)
    over = await _upload(api_env, pid, "a.wav", data)
    assert over.status_code == 422 and "大小" in assert_detail(over)
    assert _residue(workdir) == []
    monkeypatch.setattr(music_import, "MAX_UPLOAD_BYTES", len(data))
    assert (await _upload(api_env, pid, "a.wav", data)).status_code == 200


async def test_path_components_in_the_filename_are_ignored(api_env: ApiEnv, tmp_path: Path) -> None:
    pid, workdir = _mv(api_env)
    response = await _upload(api_env, pid, "../../evil.wav", _wav_bytes(tmp_path))
    assert response.status_code == 200
    assert sorted(p.name for p in (workdir / "music").iterdir()) == ["source.wav"]
    assert not (workdir.parent / "evil.wav").exists()


async def test_disconnect_mid_upload_leaves_no_temp_file(api_env: ApiEnv, tmp_path: Path) -> None:
    pid, workdir = _mv(api_env)
    data = _wav_bytes(tmp_path)
    boundary = "xBOUNDARYx"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode()

    async def body() -> AsyncIterator[bytes]:
        yield head + data[: len(data) // 2]
        raise ConnectionError("client went away")

    with pytest.raises(Exception):  # noqa: B017,PT011 - the client side error is not the point
        await api_env.client.post(
            _url(pid),
            content=body(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    assert _residue(workdir) == []
    assert not (workdir / "music" / "source.wav").exists()
    assert pid not in api_env.app.state.music_uploads


def test_fixture_tools_exist() -> None:
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
