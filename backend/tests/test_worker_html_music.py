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
from fixtures.import_music import write_mv_workspace
from fixtures.import_music.seed import seed_mv_project
from fixtures.synth_music import seed
from fixtures.synth_music.products import render_free_products, render_products
from studio.db.engine import make_engine, migrate
from studio.engines.render.mix import MV_FADE_IN, MV_FADE_OUT, AudioTrack, MusicMix
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
    await render_free_products(env.workdir)
    (env.workdir / "animation").mkdir(exist_ok=True)
    (env.workdir / "animation" / "shots.json").write_text(json.dumps(seed.SHOTS), encoding="utf-8")
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
    assert music.track.gain_db == 0.0 and music.duck_under_narration is False
    final = json.loads((reel.workdir / "output" / "final.json").read_text())
    assert final["audio_sources"] == {}  # no narration clips
    assert final["music_hash"] == _sha(reel.workdir / "music" / "music.wav")
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
    assert final["music_hash"] == _sha(bed.workdir / "music" / "music.wav")
    assert set(final["audio_sources"]) == {"s-hook", "s-explain"}  # clips only, no "music" key


async def test_an_explainer_without_music_is_mixed_as_before(plain: Env) -> None:
    backend = FakeBackend()
    assert _job(plain, await _run(plain, backend)).status == "done"
    assert backend.mix_calls[0]["music"] is None
    final = json.loads((plain.workdir / "output" / "final.json").read_text())
    assert "music_hash" not in final


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
    elif how == "shots-short":  # the shots no longer cover the rendered audio
        path = env.workdir / "animation" / "shots.json"
        path.write_text(path.read_text().replace('"end": 16.0', '"end": 12.0', 1), encoding="utf-8")
    elif how == "shots-missing":
        (env.workdir / "animation" / "shots.json").unlink()
    elif how == "scene-missing":
        (env.workdir / "animation" / "scenes" / "s2.js").unlink()
    elif how == "script-edited":  # compose.py changed after the last render
        with (music / "compose.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# edited after the render\n")
    elif how == "script-missing":
        (music / "compose.py").unlink()
    elif how == "script-hash-missing":
        record = json.loads((music / "render.json").read_text(encoding="utf-8"))
        del record["script_hash"]
        (music / "render.json").write_text(json.dumps(record), encoding="utf-8")
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
        ("shots-short", "到「配乐与动画」阶段重新渲染或调整镜头"),
        ("shots-missing", "animation/shots.json"),
        ("scene-missing", "s2"),
        ("wav-replaced", "music.wav 与 render.json 记录的不一致"),
        ("script-edited", "music/compose.py 在上次渲染之后改过，需要在配乐与动画阶段重新渲染"),
        ("script-missing", "music/compose.py 在上次渲染之后改过，需要在配乐与动画阶段重新渲染"),
        ("script-hash-missing", "music/render.json 损坏或缺字段"),
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


@pytest.mark.parametrize("how", ["script-edited", "script-missing"])
async def test_an_explainer_bed_with_a_changed_script_asks_for_a_new_render(
    bed: Env, how: str
) -> None:
    _break(bed, how)
    backend = FakeBackend()
    job = _job(bed, await _run(bed, backend))
    assert job.status == "failed"
    assert "music/compose.py 在上次渲染之后改过，需要在配乐阶段重新渲染" in (job.error or ""), (
        job.error
    )
    assert backend.video_calls == [] and backend.mix_calls == []


async def test_a_stale_score_keeps_the_previous_final_video(reel: Env) -> None:
    out = reel.workdir / "output"
    out.mkdir(exist_ok=True)
    (out / "final.mp4").write_bytes(b"previous final")
    _break(reel, "shots-short")
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
    assert abs(float(info["format"]["duration"]) - 16.0) <= 0.1
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


async def test_the_mixer_gets_a_private_copy_so_a_render_in_between_cannot_change_what_is_mixed(
    reel: Env,
) -> None:
    """The hash in `final.json` must describe the bytes that were mixed. A manual render (another
    process) may replace `music/music.wav` after the pre-check, so the worker mixes a copy."""
    original = reel.workdir / "music" / "music.wav"
    before = _sha(original)
    seen: dict[str, object] = {}

    class Swapping(FakeBackend):
        async def mix(
            self,
            video: Path,
            tracks: list[AudioTrack],
            duration: float,
            output: Path,
            music: MusicMix | None = None,
        ) -> None:
            assert music is not None
            seen["path"] = music.track.path
            seen["hash"] = _sha(music.track.path)
            original.write_bytes(b"a different score rendered meanwhile")
            await super().mix(video, tracks, duration, output, music)

    job = _job(reel, await _run(reel, Swapping()))
    assert job.status == "done", job.error
    assert seen["path"] != original and seen["hash"] == before
    final = json.loads((reel.workdir / "output" / "final.json").read_text())
    assert final["music_hash"] == before
    assert not Path(str(seen["path"])).exists()  # the copy is cleaned up


# ---- imported song (4B T5) ----------------------------------------------------------------


@pytest.fixture
def mv(tmp_path: Path) -> Iterator[Env]:
    data_dir, engine, blobs = _env(tmp_path)
    pid = seed_mv_project(engine, blobs, data_dir=data_dir)
    env = Env(data_dir, engine, blobs, pid)
    write_mv_workspace(env.workdir)
    yield env
    engine.dispose()


def _final(env: Env) -> dict:
    return json.loads((env.workdir / "output" / "final.json").read_text())


async def test_a_music_video_is_mixed_from_the_range_start_of_the_song(mv: Env) -> None:
    backend = FakeBackend()
    job = _job(mv, await _run(mv, backend))
    assert job.status == "done", job.error
    [call] = backend.mix_calls
    assert call["tracks"] == [] and call["duration"] == pytest.approx(20.0)
    music = call["music"]
    assert music.track.source_start == 0.0 and music.duck_under_narration is False
    assert (music.fade_in, music.fade_out) == (MV_FADE_IN, MV_FADE_OUT)
    assert music.track.path != mv.workdir / "music" / "source.wav"
    source_hash = _sha(mv.workdir / "music" / "source.wav")
    final = _final(mv)
    assert final["audio_sources"] == {"music": {"hash": source_hash, "range": [0.0, 20.0]}}
    assert "music_hash" not in final


async def test_an_explicit_range_sets_the_start_and_the_duration(mv: Env) -> None:
    write_mv_workspace(mv.workdir, range_=(4.5, 18.5))
    backend = FakeBackend()
    job = _job(mv, await _run(mv, backend))
    assert job.status == "done", job.error
    [call] = backend.mix_calls
    assert call["music"].track.source_start == 4.5 and call["duration"] == pytest.approx(14.0)
    assert _final(mv)["audio_sources"]["music"]["range"] == [4.5, 18.5]


async def test_final_json_records_the_lyrics_only_when_there_are_lyrics(mv: Env) -> None:
    job = _job(mv, await _run(mv, FakeBackend()))
    assert job.status == "done", job.error
    assert "lyrics_hash" not in _final(mv)

    (mv.workdir / "music" / "lyrics.lrc").write_text("[00:02.00]一\n[00:08.00]二\n", "utf-8")
    first = _job(mv, await _run(mv, FakeBackend()))
    assert first.status == "done", first.error
    recorded = _final(mv)["lyrics_hash"]
    assert len(recorded) == 64

    (mv.workdir / "music" / "lyrics.lrc").write_text("[00:02.00]一\n[00:08.00]贰\n", "utf-8")
    second = _job(mv, await _run(mv, FakeBackend()))
    assert second.status == "done", second.error
    assert _final(mv)["lyrics_hash"] != recorded


@pytest.mark.parametrize(
    ("victim", "needle"),
    [
        ("music/analysis.json", "analysis.json"),
        ("animation/shots.json", "shots.json"),
        ("music/source.wav", "source"),
    ],
)
async def test_a_missing_input_stops_the_music_video_and_names_it(
    mv: Env, victim: str, needle: str
) -> None:
    (mv.workdir / victim).unlink()
    backend = FakeBackend()
    job = _job(mv, await _run(mv, backend))
    assert job.status == "failed" and needle in (job.error or ""), job.error
    assert backend.video_calls == [] and backend.mix_calls == []
    assert not (mv.workdir / "output" / "final.mp4").exists()


async def test_a_swapped_song_is_refused_and_tells_you_to_reanalyse(mv: Env) -> None:
    (mv.workdir / "music" / "source.wav").write_bytes(b"RIFF a different song")
    backend = FakeBackend()
    job = _job(mv, await _run(mv, backend))
    assert job.status == "failed" and "重新分析" in (job.error or ""), job.error
    assert backend.video_calls == [] and backend.mix_calls == []


async def test_the_music_video_mixes_a_private_copy_of_the_checked_song(mv: Env) -> None:
    original = mv.workdir / "music" / "source.wav"
    before = _sha(original)
    seen: dict[str, object] = {}

    class Swapping(FakeBackend):
        async def mix(
            self,
            video: Path,
            tracks: list[AudioTrack],
            duration: float,
            output: Path,
            music: MusicMix | None = None,
        ) -> None:
            assert music is not None
            seen["path"], seen["hash"] = music.track.path, _sha(music.track.path)
            original.write_bytes(b"swapped after the pre-check")
            await super().mix(video, tracks, duration, output, music)

    job = _job(mv, await _run(mv, Swapping()))
    assert job.status == "done", job.error
    assert seen["path"] != original and seen["hash"] == before
    assert _final(mv)["audio_sources"]["music"]["hash"] == before
    assert not Path(str(seen["path"])).exists()


async def test_the_silent_video_is_cached_until_the_range_or_the_song_changes(mv: Env) -> None:
    backend = FakeBackend()
    assert _job(mv, await _run(mv, backend)).status == "done"
    assert _job(mv, await _run(mv, backend)).status == "done"
    assert len(backend.video_calls) == 1  # identical inputs: cache hit

    write_mv_workspace(mv.workdir, range_=(4.5, 18.5))
    assert _job(mv, await _run(mv, backend)).status == "done"
    assert len(backend.video_calls) == 2  # a different range is a different film

    # the same range but another song (analysis updated to match): not a cache hit either
    from engines.audio_fixtures import SAMPLE_RATE, click_track
    from fixtures.audio_engine import write_wav

    song = write_wav(
        mv.workdir / "music" / "source.wav", click_track(120.0, 0.5, 20.0, seed=7), SAMPLE_RATE
    )
    analysis = json.loads((mv.workdir / "music" / "analysis.json").read_text())
    analysis["source_hash"] = _sha(song)
    (mv.workdir / "music" / "analysis.json").write_text(json.dumps(analysis))
    assert _job(mv, await _run(mv, backend)).status == "done"
    assert len(backend.video_calls) == 3


@pytest.mark.slow
async def test_real_render_of_a_music_video_has_the_song_as_its_audio(mv: Env) -> None:
    from studio.worker_html import real_backend

    job_id = create_job(mv.engine, type="final_render", project_id=mv.project_id, payload={}).id
    assert await run_once(mv.engine, mv.blobs, data_dir=mv.data_dir, html_backend=real_backend())
    assert _job(mv, job_id).status == "done", _job(mv, job_id).error
    final = mv.workdir / "output" / "final.mp4"
    info = _probe(final)
    assert [s["codec_name"] for s in info["streams"] if s["codec_type"] == "audio"] == ["aac"]
    assert abs(float(info["format"]["duration"]) - 20.0) <= 0.15
    assert _loudness_db(final, 1.0, 19.0) > -50  # clicks are audible, not a silent track


async def test_a_song_that_vanishes_before_the_copy_asks_for_reanalysis(
    mv: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from studio import worker_html

    def gone(source: Path, target: Path) -> str:
        raise FileNotFoundError(source)

    monkeypatch.setattr(worker_html, "_copy_with_hash", gone)
    backend = FakeBackend()
    job = _job(mv, await _run(mv, backend))
    assert job.status == "failed" and "重新分析" in (job.error or ""), job.error
    assert backend.video_calls == [] and backend.mix_calls == []
