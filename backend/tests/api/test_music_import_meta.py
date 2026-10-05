"""`GET .../music/meta|audio` for an imported song (4B T2)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fixtures.import_music import write_click_song
from fixtures.import_music.seed import seed_mv_project
from fixtures.synth_music.seed import seed_reel_project

from .conftest import ApiEnv

DURATION = 20.0
SECTIONS = {
    "sections": [
        {"id": "intro", "label": "intro", "start": 0.5, "end": 4.5},
        {"id": "verse", "label": "verse", "start": 4.5, "end": 12.5},
        {"id": "chorus", "label": "chorus", "start": 12.5, "end": 18.5},
    ]
}


def _mv(api_env: ApiEnv) -> tuple[str, Path]:
    pid = seed_mv_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    return pid, api_env.workdir(pid)


def _url(pid: str, tail: str = "meta") -> str:
    return f"/api/projects/{pid}/music/{tail}"


def _source(workdir: Path) -> str:
    (workdir / "music").mkdir(exist_ok=True)
    path = write_click_song(workdir / "music" / "source.wav")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _analysis(workdir: Path, source_hash: str, **extra: object) -> None:
    doc = {
        "source_hash": source_hash,
        "duration": DURATION,
        "bpm": 120.0,
        "offset": 0.5,
        "residual_ms": 4.0,
        "confidence": 0.9,
        "beats": [],
        "downbeats": [],
        "candidates": [],
        "hop": 0.1,
        "energy": [i / 200 for i in range(200)],
        "warnings": ["拍点不稳"],
    }
    doc.update(extra)
    (workdir / "music" / "analysis.json").write_text(json.dumps(doc), encoding="utf-8")


def _sections(workdir: Path, doc: dict | None = None) -> None:
    (workdir / "music" / "sections.json").write_text(
        json.dumps(doc if doc is not None else SECTIONS), encoding="utf-8"
    )


async def _meta(api_env: ApiEnv, pid: str) -> dict:
    response = await api_env.client.get(_url(pid))
    assert response.status_code == 200, response.text
    return response.json()


async def test_not_uploaded(api_env: ApiEnv) -> None:
    pid, _ = _mv(api_env)
    body = await _meta(api_env, pid)
    assert body["form"] == "import" and body["rendered"] is False and body["stale"] is False
    assert body["source"] is None and body["analysis"] is None and body["grid"] is None
    assert body["range"] is None and body["energy"] is None and body["sections_check"] is None
    assert body["sections"] == []


async def test_uploaded_but_not_analysed(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    digest = _source(workdir)
    body = await _meta(api_env, pid)
    assert body["rendered"] is True and body["hash"] == digest and body["stale"] is False
    source = body["source"]
    assert source["filename"] == "source.wav" and source["sha256"] == digest
    assert source["size"] == (workdir / "music" / "source.wav").stat().st_size
    assert source["duration"] is None  # only known after analysis
    assert body["analysis"] is None and body["energy"] is None and body["duration"] is None


async def test_analysed_without_sections(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    _analysis(workdir, _source(workdir))
    body = await _meta(api_env, pid)
    assert body["analysis"] == {
        "bpm": 120.0,
        "confidence": 0.9,
        "residual_ms": 4.0,
        "duration": DURATION,
        "warnings": ["拍点不稳"],
    }
    assert body["source"]["duration"] == DURATION and body["duration"] == DURATION
    assert body["energy"]["hop"] == 0.1 and len(body["energy"]["values"]) == 200
    assert body["grid"]["bpm"] == 120.0 and body["grid"]["offset"] == 0.5
    assert body["grid"]["downbeats"][:3] == [0.5, 2.5, 4.5]
    assert body["sections"] == [] and body["range"] is None
    assert body["sections_check"]["ok"] is False  # sections.json is missing


async def test_analysed_with_valid_sections(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    _analysis(workdir, _source(workdir))
    _sections(workdir)
    body = await _meta(api_env, pid)
    assert body["sections_check"]["ok"] is True and body["sections_check"]["errors"] == []
    assert [s["id"] for s in body["sections"]] == ["intro", "verse", "chorus"]
    assert body["sections"][1]["start"] == 4.5  # whole-song seconds, not range-relative
    assert body["range"] == {"start": 0.5, "end": 18.5}
    assert body["stale"] is False


async def test_explicit_range_and_grid_override_win(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    _analysis(workdir, _source(workdir))
    doc = {**SECTIONS, "bpm": 60.0, "offset": 0.5, "range": {"start": 0.5, "end": 18.5}}
    _sections(workdir, doc)
    body = await _meta(api_env, pid)
    assert body["grid"]["bpm"] == 60.0
    assert body["grid"]["downbeats"][:3] == [0.5, 4.5, 8.5]
    assert body["range"] == {"start": 0.5, "end": 18.5}


async def test_sections_check_reports_errors(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    _analysis(workdir, _source(workdir))
    _sections(workdir, {"sections": [{"id": "a", "label": "a", "start": 0.7, "end": 4.5}]})
    body = await _meta(api_env, pid)
    assert body["sections_check"]["ok"] is False and body["sections_check"]["errors"]


async def test_changed_song_is_stale(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    _source(workdir)
    _analysis(workdir, "0" * 64)
    _sections(workdir)
    body = await _meta(api_env, pid)
    assert body["stale"] is True
    assert body["source"]["duration"] is None  # the analysis does not describe this file


@pytest.mark.parametrize("victim", ["analysis.json", "sections.json"])
async def test_corrupt_documents_degrade_to_empty_fields(api_env: ApiEnv, victim: str) -> None:
    pid, workdir = _mv(api_env)
    _analysis(workdir, _source(workdir))
    _sections(workdir)
    (workdir / "music" / victim).write_text("{broken", encoding="utf-8")
    body = await _meta(api_env, pid)
    assert body["source"] is not None and body["sections_check"]["ok"] is False


async def test_audio_serves_source_with_range_and_media_type(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    _source(workdir)
    data = (workdir / "music" / "source.wav").read_bytes()
    full = await api_env.client.get(_url(pid, "audio"))
    assert full.status_code == 200 and full.headers["content-type"] == "audio/wav"
    assert full.headers["cache-control"] == "no-store" and full.content == data
    part = await api_env.client.get(_url(pid, "audio"), headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == data[:100]


async def test_audio_without_source_is_404(api_env: ApiEnv) -> None:
    pid, _ = _mv(api_env)
    assert (await api_env.client.get(_url(pid, "audio"))).status_code == 404


async def test_render_is_404_for_import(api_env: ApiEnv) -> None:
    pid, _ = _mv(api_env)
    response = await api_env.client.post(_url(pid, "render"))
    assert response.status_code == 404 and "合成" in response.json()["detail"]


async def test_synth_form_reports_form_synth(api_env: ApiEnv) -> None:
    pid = seed_reel_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    body = await _meta(api_env, pid)
    assert body["form"] == "synth" and body["source"] is None


async def test_non_numeric_energy_degrades_to_no_energy(api_env: ApiEnv) -> None:
    pid, workdir = _mv(api_env)
    _analysis(workdir, _source(workdir), energy=[0.1, None, "x"])
    body = await _meta(api_env, pid)
    assert body["energy"] is None and body["analysis"] is not None


async def test_render_of_an_import_project_says_there_is_no_synth_render(api_env: ApiEnv) -> None:
    pid, _ = _mv(api_env)
    response = await api_env.client.post(_url(pid, "render"))
    assert response.status_code == 404 and response.json()["detail"] == "导入形态没有合成渲染"
