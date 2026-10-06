"""`/api/projects/{id}/music/*`（3B T3）：元数据、音频（Range）与不经 agent 的手动渲染。"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from fixtures.synth_music import seed
from fixtures.synth_music.products import FREE, render_free_products
from studio.stages.common.score import tool as music_tool

from .conftest import ApiEnv


def _identity(workdir: Path):
    def wrap(argv: list[str], env: dict[str, str]) -> list[str]:
        return argv

    return wrap


@pytest.fixture(autouse=True)
def plain_scripts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(music_tool, "sandbox_wrapper", _identity)


async def _reel(api_env: ApiEnv, *, render: bool = True) -> tuple[str, Path]:
    engine, blobs = api_env.app.state.engine, api_env.app.state.blobs
    pid = seed.seed_reel_project(engine, blobs, data_dir=api_env.data_dir)
    workdir = api_env.workdir(pid)
    (workdir / "animation").mkdir(exist_ok=True)
    (workdir / "animation" / "shots.json").write_text(json.dumps(seed.SHOTS), encoding="utf-8")
    if render:
        await render_free_products(workdir)
    else:
        (workdir / "music").mkdir()
        shutil.copyfile(FREE, workdir / "music" / "compose.py")
    return pid, workdir


def _url(pid: str, tail: str) -> str:
    return f"/api/projects/{pid}/music/{tail}"


# ---- meta ---------------------------------------------------------------------------------


async def test_meta_describes_the_rendered_score(api_env: ApiEnv) -> None:
    pid, workdir = await _reel(api_env)
    body = (await api_env.client.get(_url(pid, "meta"))).json()
    render = json.loads((workdir / "music" / "render.json").read_text())
    assert body["rendered"] is True and body["stale"] is False
    assert body["hash"] == render["wav_hash"]
    assert body["bpm"] == 120 and body["duration"] == pytest.approx(16.0, abs=0.02)
    assert len(body["waveform"]) == 1000 and body["events"]
    assert {"name", "kind", "start", "end"} <= set(body["events"][0])
    assert [s["id"] for s in body["sections"]] == ["s1", "s2"]
    assert "rms_dbfs" in body["metrics"]


async def test_meta_without_products_says_not_rendered(api_env: ApiEnv) -> None:
    pid, _ = await _reel(api_env, render=False)
    response = await api_env.client.get(_url(pid, "meta"))
    assert response.status_code == 200
    body = response.json()
    assert body["rendered"] is False and body["events"] == [] and body["waveform"] == []
    assert [s["id"] for s in body["sections"]] == ["s1", "s2"]  # the script tab still has them


async def test_meta_without_bpm_still_describes_the_score(api_env: ApiEnv) -> None:
    pid, workdir = await _reel(api_env)
    path = workdir / "music" / "render.json"
    record = json.loads(path.read_text())
    record["bpm"] = None
    path.write_text(json.dumps(record))
    body = (await api_env.client.get(_url(pid, "meta"))).json()
    assert body["rendered"] is True and body["bpm"] is None and body["stale"] is False


async def test_meta_does_not_need_a_timeline_to_be_usable(api_env: ApiEnv) -> None:
    """The score and the shots are both the model's own work: a broken shots file does not make
    the rendered score stale, the sections are simply empty."""
    pid, workdir = await _reel(api_env)
    (workdir / "animation" / "shots.json").write_text("{not json", encoding="utf-8")
    body = (await api_env.client.get(_url(pid, "meta"))).json()
    assert body["rendered"] is True and body["stale"] is False and body["sections"] == []


async def test_meta_survives_corrupt_products(api_env: ApiEnv) -> None:
    pid, workdir = await _reel(api_env)
    (workdir / "music" / "analysis.json").write_text("{not json", encoding="utf-8")
    body = (await api_env.client.get(_url(pid, "meta"))).json()
    assert body["rendered"] is False


@pytest.mark.parametrize("path", ["meta", "audio"])
async def test_projects_without_a_score_have_no_music_endpoints(api_env: ApiEnv, path: str) -> None:
    project = await api_env.create_project()
    assert (await api_env.client.get(_url(project["id"], path))).status_code == 404
    assert (await api_env.client.get(_url("nope", path))).status_code == 404


# ---- audio --------------------------------------------------------------------------------


async def test_audio_serves_the_wav_with_range_support(api_env: ApiEnv) -> None:
    pid, workdir = await _reel(api_env)
    wav = (workdir / "music" / "music.wav").read_bytes()
    client = api_env.client

    full = await client.get(_url(pid, "audio"))
    assert full.status_code == 200 and full.content == wav
    assert full.headers["content-type"].startswith("audio/")
    assert full.headers["cache-control"] == "no-store"
    assert full.headers["accept-ranges"] == "bytes"

    part = await client.get(_url(pid, "audio"), headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == wav[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(wav)}"

    tail = await client.get(_url(pid, "audio"), headers={"Range": "bytes=-50"})
    assert tail.status_code == 206 and tail.content == wav[-50:]


@pytest.mark.parametrize("value", ["bytes=999999999-", "bytes=abc", "bytes=5-2"])
async def test_audio_refuses_an_unsatisfiable_or_malformed_range(
    api_env: ApiEnv, value: str
) -> None:
    pid, _ = await _reel(api_env)
    response = await api_env.client.get(_url(pid, "audio"), headers={"Range": value})
    assert response.status_code in (400, 416)


async def test_audio_without_a_rendered_score_is_404(api_env: ApiEnv) -> None:
    pid, _ = await _reel(api_env, render=False)
    assert (await api_env.client.get(_url(pid, "audio"))).status_code == 404


async def test_audio_never_leaves_the_music_wav(api_env: ApiEnv) -> None:
    pid, workdir = await _reel(api_env)
    (workdir / "music" / "music.wav").unlink()
    (workdir / "secret.txt").write_text("nope")
    (workdir / "music" / "music.wav").symlink_to(workdir / "secret.txt")  # escapes via link
    response = await api_env.client.get(_url(pid, "audio"))
    assert response.status_code == 404 and b"nope" not in response.content


# ---- render -------------------------------------------------------------------------------


async def test_render_runs_the_script_and_returns_the_report(api_env: ApiEnv) -> None:
    pid, workdir = await _reel(api_env, render=False)
    response = await api_env.client.post(_url(pid, "render"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["errors"] == []
    assert "配乐渲染成功" in body["text"] and body["retime_note"] == ""
    assert body["metrics"]["onsets"] > 0
    jpeg = base64.b64decode(body["picture_base64"])
    assert body["picture_media_type"] == "image/jpeg" and jpeg[:3] == b"\xff\xd8\xff"
    assert len(jpeg) <= 400_000
    for name in ("music.wav", "events.json", "analysis.json", "analysis.png", "render.json"):
        assert (workdir / "music" / name).is_file()
    assert (await api_env.client.get(_url(pid, "meta"))).json()["rendered"] is True


async def test_a_failing_script_is_a_business_result_and_keeps_the_old_products(
    api_env: ApiEnv,
) -> None:
    pid, workdir = await _reel(api_env)
    before = {p.name: p.read_bytes() for p in (workdir / "music").iterdir() if p.is_file()}
    (workdir / "music" / "compose.py").write_text("raise RuntimeError('boom in script')\n")
    response = await api_env.client.post(_url(pid, "render"))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False and any("boom in script" in e for e in body["errors"])
    assert body["picture_base64"] is None
    after = {p.name: p.read_bytes() for p in (workdir / "music").iterdir() if p.is_file()}
    after.pop("compose.py")
    before.pop("compose.py")
    assert after == before


async def test_render_without_a_script_says_so(api_env: ApiEnv) -> None:
    pid, workdir = await _reel(api_env, render=False)
    (workdir / "music" / "compose.py").unlink()
    body = (await api_env.client.post(_url(pid, "render"))).json()
    assert body["ok"] is False and any("compose.py" in e for e in body["errors"])


async def test_render_is_refused_while_a_turn_runs(api_env: ApiEnv) -> None:
    pid, _ = await _reel(api_env, render=False)
    turn_id = await api_env.make_busy(pid, stage="music")
    try:
        response = await api_env.client.post(_url(pid, "render"))
    finally:
        await api_env.release_busy(turn_id)
    assert response.status_code == 409 and "一轮" in response.json()["detail"]


async def test_render_is_refused_without_a_sandbox(
    api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, _ = await _reel(api_env, render=False)
    monkeypatch.setattr(music_tool, "sandbox_wrapper", lambda workdir: None)
    response = await api_env.client.post(_url(pid, "render"))
    assert response.status_code == 409 and "沙箱" in response.json()["detail"]


async def test_a_second_render_while_one_runs_is_refused(
    api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from studio.api import music as music_api

    pid, _ = await _reel(api_env, render=False)
    started, release = asyncio.Event(), asyncio.Event()
    real = music_api.render_music_core

    async def slow(*args, **kwargs):
        started.set()
        await release.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(music_api, "render_music_core", slow)
    first = asyncio.create_task(api_env.client.post(_url(pid, "render")))
    await started.wait()
    second = await api_env.client.post(_url(pid, "render"))
    release.set()
    assert second.status_code == 409 and "正在渲染" in second.json()["detail"]
    assert (await first).status_code == 200


async def test_a_reel_render_needs_no_timeline(api_env: ApiEnv) -> None:
    """The script picks tempo and length itself: the endpoint works with no shots yet."""
    pid, workdir = await _reel(api_env, render=False)
    (workdir / "animation" / "shots.json").unlink()
    body = (await api_env.client.post(_url(pid, "render"))).json()
    assert body["ok"] is True, body


async def test_render_hash_matches_what_the_worker_checks(api_env: ApiEnv) -> None:
    """The endpoint's products pass the same wav check as the preview and the final render."""
    pid, workdir = await _reel(api_env, render=False)
    await api_env.client.post(_url(pid, "render"))
    render = json.loads((workdir / "music" / "render.json").read_text())
    wav = hashlib.sha256((workdir / "music" / "music.wav").read_bytes()).hexdigest()
    assert render["wav_hash"] == wav
    assert (await api_env.client.get(_url(pid, "meta"))).json()["stale"] is False


async def test_meta_marks_a_replaced_wav_as_stale_like_the_preview_and_the_render_do(
    api_env: ApiEnv,
) -> None:
    pid, workdir = await _reel(api_env)
    wav = workdir / "music" / "music.wav"
    data = bytearray(wav.read_bytes())
    data[-5] ^= 0x7F
    wav.write_bytes(bytes(data))
    body = (await api_env.client.get(_url(pid, "meta"))).json()
    assert body["rendered"] is True and body["stale"] is True
    preview = (await api_env.client.get(f"/api/projects/{pid}/animation/html-preview/meta")).json()
    assert preview["music"] is None
