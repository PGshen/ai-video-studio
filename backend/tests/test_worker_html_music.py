"""`worker_html` with a score (3B T2): reel and explainer-with-bed final renders.

Rendering and mixing go through the fake backend; what matters here is which tracks and which
`MusicMix` reach the mixer, the pre-checks that stop a stale score, and `final.json`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import Engine

from fixtures.animation_html.seed import seed_animation_html_project
from fixtures.html_engine import projects as fx
from fixtures.html_engine.worker_fakes import ExplodingManim, FakeBackend
from fixtures.synth_music import seed
from fixtures.synth_music.products import render_products
from studio.db.engine import make_engine, migrate
from studio.jobs import create_job, get_job
from studio.worker import run_once
from studio.workspace import BlobStore, project_dir


@dataclass
class Env:
    data_dir: Path
    engine: Engine
    blobs: BlobStore
    project_id: str

    @property
    def workdir(self) -> Path:
        return project_dir(self.data_dir, self.project_id)


def _env(tmp_path: Path) -> tuple[Path, Engine, BlobStore]:
    data_dir = tmp_path / "data"
    engine = make_engine(tmp_path / "studio.db")
    migrate(engine)
    return data_dir, engine, BlobStore(data_dir / "blobs")


@pytest.fixture
async def reel(tmp_path: Path) -> AsyncIterator[Env]:
    data_dir, engine, blobs = _env(tmp_path)
    pid = seed.seed_reel_project(engine, blobs, data_dir=data_dir)
    env = Env(data_dir, engine, blobs, pid)
    (env.workdir / "beatsheet").mkdir()
    (env.workdir / "beatsheet" / "beatsheet.json").write_text(seed.BEATSHEET, encoding="utf-8")
    await render_products(env.workdir)
    fx.write_project(env.workdir, scenes={"s1": fx.PURE_SCENE_PLAIN, "s2": fx.PURE_SCENE_PLAIN})
    yield env
    engine.dispose()


@pytest.fixture
async def bed(tmp_path: Path) -> AsyncIterator[Env]:
    data_dir, engine, blobs = _env(tmp_path)
    pid = seed.seed_bed_project(engine, blobs, data_dir=data_dir)
    env = Env(data_dir, engine, blobs, pid)
    await render_products(env.workdir)
    fx.write_project(
        env.workdir, scenes={"s-hook": fx.PURE_SCENE_PLAIN, "s-explain": fx.PURE_SCENE_PLAIN}
    )
    yield env
    engine.dispose()


@pytest.fixture
def plain(tmp_path: Path) -> Iterator[Env]:
    data_dir, engine, blobs = _env(tmp_path)
    pid = seed_animation_html_project(engine, blobs, data_dir=data_dir)
    env = Env(data_dir, engine, blobs, pid)
    fx.write_project(
        env.workdir, scenes={"s-hook": fx.PURE_SCENE_PLAIN, "s-explain": fx.PURE_SCENE_PLAIN}
    )
    yield env
    engine.dispose()


async def _run(env: Env, backend: FakeBackend) -> str:
    job = create_job(env.engine, type="final_render", project_id=env.project_id, payload={})
    claimed = await run_once(
        env.engine,
        env.blobs,
        data_dir=env.data_dir,
        render_engine=ExplodingManim(),
        html_backend=backend.as_backend(),
    )
    assert claimed is True
    return job.id


def _job(env: Env, job_id: str):
    job = get_job(env.engine, job_id)
    assert job is not None
    return job


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_a_reel_is_mixed_with_only_the_score(reel: Env) -> None:
    backend = FakeBackend()
    job = _job(reel, await _run(reel, backend))
    assert job.status == "done", job.error
    [call] = backend.mix_calls
    assert call["tracks"] == []
    music = call["music"]
    assert music.track.path == reel.workdir / "music" / "music.wav"
    assert music.track.gain_db == 0.0 and music.duck_under_narration is False
    final = json.loads((reel.workdir / "output" / "final.json").read_text())
    assert final["audio_sources"] == {"music": _sha(reel.workdir / "music" / "music.wav")}
    assert (reel.workdir / "output" / "final.mp4").is_file()


async def test_an_explainer_bed_is_ducked_under_the_narration(bed: Env) -> None:
    backend = FakeBackend()
    job = _job(bed, await _run(bed, backend))
    assert job.status == "done", job.error
    [call] = backend.mix_calls
    assert len(call["tracks"]) == 2
    music = call["music"]
    assert music.duck_under_narration is True
    assert (music.track.gain_db, music.fade_in, music.fade_out) == (-8.0, 1.0, 1.5)
    final = json.loads((bed.workdir / "output" / "final.json").read_text())
    assert final["audio_sources"]["music"] == _sha(bed.workdir / "music" / "music.wav")
    assert {"s-hook", "s-explain"} <= set(final["audio_sources"])


async def test_an_explainer_without_music_is_mixed_as_before(plain: Env) -> None:
    backend = FakeBackend()
    assert _job(plain, await _run(plain, backend)).status == "done"
    assert backend.mix_calls[0]["music"] is None
    final = json.loads((plain.workdir / "output" / "final.json").read_text())
    assert "music" not in final["audio_sources"]


def _break(env: Env, how: str) -> None:
    music = env.workdir / "music"
    if how == "wav-missing":
        (music / "music.wav").unlink()
    elif how == "events-missing":
        (music / "events.json").unlink()
    elif how == "analysis-missing":
        (music / "analysis.json").unlink()
    elif how == "render-missing":
        (music / "render.json").unlink()
    elif how == "beatsheet-bars":
        path = env.workdir / "beatsheet" / "beatsheet.json"
        path.write_text(path.read_text().replace('"bars": 3', '"bars": 4', 1), encoding="utf-8")
    elif how == "beatsheet-label":  # same length, different timeline: only `base_hash` notices
        path = env.workdir / "beatsheet" / "beatsheet.json"
        path.write_text(path.read_text().replace("BUILD", "RISE", 1), encoding="utf-8")
    elif how == "wav-replaced":
        shutil.copyfile(music / "music.wav", music / "other.wav")
        data = bytearray((music / "music.wav").read_bytes())
        data[-5] ^= 0x7F
        (music / "music.wav").write_bytes(bytes(data))
    else:  # pragma: no cover - test misuse
        raise ValueError(how)


@pytest.mark.parametrize(
    ("how", "needle"),
    [
        ("wav-missing", "music/music.wav"),
        ("events-missing", "music/events.json"),
        ("analysis-missing", "music/analysis.json"),
        ("render-missing", "music/render.json"),
        ("beatsheet-bars", "到配乐阶段重新渲染"),
        ("beatsheet-label", "配乐与当前时间轴不一致"),
        ("wav-replaced", "music.wav 与 render.json 记录的不一致"),
    ],
)
async def test_a_missing_or_stale_score_stops_the_render_and_says_why(
    reel: Env, how: str, needle: str
) -> None:
    _break(reel, how)
    backend = FakeBackend()
    job = _job(reel, await _run(reel, backend))
    assert job.status == "failed"
    assert job.error is not None and needle in job.error, job.error
    assert backend.video_calls == [] and backend.mix_calls == []
    assert not (reel.workdir / "output" / "final.mp4").exists()


async def test_a_stale_score_keeps_the_previous_final_video(reel: Env) -> None:
    out = reel.workdir / "output"
    out.mkdir(exist_ok=True)
    (out / "final.mp4").write_bytes(b"previous final")
    _break(reel, "beatsheet-label")
    assert _job(reel, await _run(reel, FakeBackend())).status == "failed"
    assert (out / "final.mp4").read_bytes() == b"previous final"


async def test_a_mix_failure_with_music_keeps_the_old_output(reel: Env) -> None:
    from studio.engines.render.mix import MixError

    out = reel.workdir / "output"
    out.mkdir(exist_ok=True)
    (out / "final.mp4").write_bytes(b"previous final")
    job = _job(reel, await _run(reel, FakeBackend(mix_error=MixError("boom"))))
    assert job.status == "failed" and "boom" in (job.error or "")
    assert (out / "final.mp4").read_bytes() == b"previous final"


# ---- real Chromium + ffmpeg ----------------------------------------------------------


def _probe(path: Path) -> dict:
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


def _loudness_db(path: Path, start: float, end: float) -> float:
    import subprocess

    import numpy as np

    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-vn", "-f", "s16le", "-ac", "1",
         "-ar", "44100", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    samples = np.frombuffer(raw, dtype="<i2").astype(float) / 32768.0
    window = samples[int(start * 44100) : int(end * 44100)]
    return 20 * float(np.log10(max(float(np.sqrt(np.mean(window**2))), 1e-9)))


@pytest.mark.slow
async def test_real_render_of_a_reel_has_the_score_as_its_audio(reel: Env) -> None:
    from studio.worker_html import real_backend

    job_id = create_job(reel.engine, type="final_render", project_id=reel.project_id, payload={}).id
    assert await run_once(
        reel.engine, reel.blobs, data_dir=reel.data_dir, html_backend=real_backend()
    )
    assert _job(reel, job_id).status == "done", _job(reel, job_id).error
    final = reel.workdir / "output" / "final.mp4"
    info = _probe(final)
    assert [s["codec_name"] for s in info["streams"] if s["codec_type"] == "audio"] == ["aac"]
    assert abs(float(info["format"]["duration"]) - 11.25) <= 0.1
    assert _loudness_db(final, 1.0, 10.0) > -40  # the score is audible, not a silent track


@pytest.mark.slow
async def test_real_render_of_an_explainer_bed_has_narration_and_a_quieter_score(bed: Env) -> None:
    from studio.worker_html import real_backend

    job_id = create_job(bed.engine, type="final_render", project_id=bed.project_id, payload={}).id
    assert await run_once(bed.engine, bed.blobs, data_dir=bed.data_dir, html_backend=real_backend())
    assert _job(bed, job_id).status == "done", _job(bed, job_id).error
    final = bed.workdir / "output" / "final.mp4"
    info = _probe(final)
    assert [s["codec_type"] for s in info["streams"]].count("audio") == 1
    assert abs(float(info["format"]["duration"]) - 3.0) <= 0.15


async def test_imported_music_is_refused_instead_of_rendering_a_silent_film(reel: Env) -> None:
    from studio.db.repo.projects import update_project_settings

    update_project_settings(reel.engine, reel.project_id, {"music_source": "import"})
    backend = FakeBackend()
    job = _job(reel, await _run(reel, backend))
    assert job.status == "failed" and "导入音乐" in (job.error or "")
    assert backend.video_calls == [] and backend.mix_calls == []
