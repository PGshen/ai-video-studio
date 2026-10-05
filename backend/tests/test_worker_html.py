"""`studio.worker` 的 HTML 成片路径（2B T3）：分流、前置检查、缓存、混音与 `final.json`。

渲染与混音用假后端（写几个字节），不起 Chromium 和 ffmpeg；真实端到端见
`tests/api/test_html_final_flow.py`（slow）。
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from fixtures.animation_html.seed import seed_animation_html_project
from fixtures.html_engine import projects as fx
from studio.db.engine import make_engine, migrate, session_scope
from studio.db.models import Job
from studio.db.repo.snapshots import latest_snapshot
from studio.engines.render.base import (
    PreviewRequest,
    PreviewResult,
    RenderRequest,
    RenderResult,
    SceneInput,
)
from studio.engines.render.html.assemble import AssembledPage
from studio.engines.render.html.video import VideoRenderError
from studio.engines.render.mix import AudioTrack, MixError
from studio.jobs import create_job, get_job
from studio.worker import run_once
from studio.worker_html import HtmlBackend
from studio.workspace import BlobStore, project_dir


@dataclass
class HtmlEnv:
    data_dir: Path
    engine: Engine
    blobs: BlobStore
    project_id: str

    @property
    def workdir(self) -> Path:
        return project_dir(self.data_dir, self.project_id)


@pytest.fixture
def html_env(tmp_path: Path) -> Iterator[HtmlEnv]:
    data_dir = tmp_path / "data"
    engine = make_engine(tmp_path / "studio.db")
    migrate(engine)
    blobs = BlobStore(data_dir / "blobs")
    project_id = seed_animation_html_project(engine, blobs, data_dir=data_dir)
    fx.write_project(
        project_dir(data_dir, project_id),
        scenes={"s-hook": fx.PURE_SCENE_PLAIN, "s-explain": fx.PURE_SCENE_PLAIN},
    )
    yield HtmlEnv(data_dir, engine, blobs, project_id)
    engine.dispose()


@dataclass
class FakeBackend:
    video_calls: list[dict[str, Any]] = field(default_factory=list)
    mix_calls: list[dict[str, Any]] = field(default_factory=list)
    video_error: Exception | None = None
    mix_error: Exception | None = None
    on_video: Any = None

    async def render_video(
        self, page: AssembledPage, duration: float, output: Path, fps: int, on_progress: Any
    ) -> None:
        self.video_calls.append({"page": page, "duration": duration, "fps": fps})
        if self.on_video is not None:
            await self.on_video(on_progress)
        if self.video_error is not None:
            raise self.video_error
        output.parent.mkdir(parents=True, exist_ok=True)  # like render_silent_video
        output.write_bytes(b"silent-video")

    async def mix(
        self, video: Path, tracks: list[AudioTrack], duration: float, output: Path
    ) -> None:
        self.mix_calls.append({"video": video, "tracks": tracks, "duration": duration})
        if self.mix_error is not None:
            raise self.mix_error
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"final-video:" + video.read_bytes())

    def as_backend(self) -> HtmlBackend:
        return HtmlBackend(render_video=self.render_video, mix=self.mix)


class ExplodingManim:
    """HTML 项目绝不能碰 Manim 引擎。"""

    engine_name = "exploding"

    async def validate_code(self, scenes: list[SceneInput]) -> tuple[bool, str]:
        raise AssertionError("manim engine used for an html project")

    async def render_preview(self, request: PreviewRequest) -> PreviewResult:
        raise AssertionError("manim engine used for an html project")

    async def health_check(self) -> bool:
        raise AssertionError("manim engine used for an html project")

    async def render(self, request: RenderRequest, work_dir: str | None = None) -> RenderResult:
        raise AssertionError("manim engine used for an html project")


async def _run(env: HtmlEnv, backend: FakeBackend) -> str:
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


def _job(env: HtmlEnv, job_id: str):
    job = get_job(env.engine, job_id)
    assert job is not None
    return job


async def test_html_project_is_rendered_mixed_and_described(html_env: HtmlEnv) -> None:
    backend = FakeBackend()
    job_id = await _run(html_env, backend)

    job = _job(html_env, job_id)
    assert job.status == "done", job.error
    assert job.result == {"output_path": "output/final.mp4"}
    final = html_env.workdir / "output" / "final.mp4"
    assert final.read_bytes() == b"final-video:silent-video"

    meta = json.loads((html_env.workdir / "output" / "final.json").read_text())
    snapshot = latest_snapshot(html_env.engine, html_env.project_id)
    assert snapshot is not None
    assert meta["snapshot_id"] == snapshot.id
    assert meta["engine"] == "html"
    assert len(meta["timeline_hash"]) == 64
    assert set(meta["audio_sources"]) == {"s-hook", "s-explain"}
    assert set(meta["scene_hashes"]) == {"s-hook", "s-explain"}
    assert "rendered_at" in meta

    (call,) = backend.mix_calls
    assert [round(t.start, 3) for t in call["tracks"]] == [0.0, 1.4]  # timeline order and starts
    assert [round(t.max_seconds, 3) for t in call["tracks"]] == [
        1.4,
        1.6,
    ]  # each clip ends with its scene
    assert call["duration"] == pytest.approx(3.0)
    assert all(t.path.is_file() for t in call["tracks"])
    assert backend.video_calls[0]["duration"] == pytest.approx(3.0)
    # The frames are rendered from the very page the cache key was computed from.
    assert "animation/scenes/s-hook.js" in backend.video_calls[0]["page"].scripts
    assert backend.video_calls[0]["fps"] == 30


@pytest.mark.parametrize(
    ("break_project", "needle"),
    [
        (lambda wd: (wd / "animation/scenes/s-explain.js").unlink(), "s-explain"),
        (lambda wd: (wd / "animation/scenes/s-hook.js").write_text("  \n"), "s-hook"),
        (
            lambda wd: (wd / "animation/scenes/s-hook.js").write_text(
                "module.exports = { draw(ctx) { Math.random(); } };\n"
            ),
            "Math.random",
        ),
        (
            lambda wd: (wd / "narrative/timing.json").write_text(
                json.dumps(
                    {
                        "scenes": [
                            s
                            for s in json.loads((wd / "narrative/timing.json").read_text())[
                                "scenes"
                            ]
                            if s["id"] != "s-explain"
                        ]
                    }
                )
            ),
            "s-explain",
        ),
        (lambda wd: (wd / "narrative/audio/s-hook.wav").unlink(), "s-hook"),
        (
            lambda wd: (
                (wd / "animation/assets").mkdir() or (wd / "animation/assets/x.gif").write_text("x")
            ),
            "x.gif",
        ),
    ],
    ids=[
        "missing-scene",
        "empty-scene",
        "static-error",
        "timing-mismatch",
        "audio-missing",
        "bad-asset",
    ],
)
async def test_precheck_failures_name_the_problem_and_never_open_a_browser(
    html_env: HtmlEnv, break_project: Any, needle: str
) -> None:
    before = latest_snapshot(html_env.engine, html_env.project_id)
    break_project(html_env.workdir)
    backend = FakeBackend()
    job_id = await _run(html_env, backend)

    job = _job(html_env, job_id)
    assert job.status == "failed"
    assert job.error is not None and needle in job.error
    assert backend.video_calls == [] and backend.mix_calls == []
    assert not (html_env.workdir / "output" / "final.mp4").exists()
    after = latest_snapshot(html_env.engine, html_env.project_id)
    assert before is not None and after is not None and after.id == before.id


async def test_second_render_with_nothing_changed_skips_the_frames_but_remixes(
    html_env: HtmlEnv,
) -> None:
    backend = FakeBackend()
    await _run(html_env, backend)
    await _run(html_env, backend)
    assert len(backend.video_calls) == 1
    assert len(backend.mix_calls) == 2


async def test_changing_a_scene_lib_or_the_timeline_invalidates_the_cache(
    html_env: HtmlEnv,
) -> None:
    backend = FakeBackend()
    await _run(html_env, backend)

    (html_env.workdir / "animation/scenes/s-hook.js").write_text(
        fx.PURE_SCENE_PLAIN + "\n// edit\n"
    )
    await _run(html_env, backend)
    assert len(backend.video_calls) == 2

    (html_env.workdir / "animation/lib").mkdir()
    (html_env.workdir / "animation/lib/a.js").write_text("const A = 1;\n")
    await _run(html_env, backend)
    assert len(backend.video_calls) == 3

    timing_path = html_env.workdir / "narrative/timing.json"
    timing = json.loads(timing_path.read_text())
    timing["scenes"][1]["duration_seconds"] += 0.5
    timing_path.write_text(json.dumps(timing))
    await _run(html_env, backend)
    assert len(backend.video_calls) == 4


async def test_render_failure_fails_the_job_and_keeps_old_output_and_cache_clean(
    html_env: HtmlEnv,
) -> None:
    output = html_env.workdir / "output"
    output.mkdir()
    (output / "final.mp4").write_bytes(b"old")
    backend = FakeBackend(
        video_error=VideoRenderError("第 3 帧（t=0.100s）渲染失败：[scene s-hook @lt=0.1] boom")
    )
    job_id = await _run(html_env, backend)

    job = _job(html_env, job_id)
    assert job.status == "failed"
    assert job.error is not None and "s-hook" in job.error and "t=0.100" in job.error
    assert (output / "final.mp4").read_bytes() == b"old"
    cache = html_env.workdir / ".cache" / "render_cache"
    assert not cache.exists() or not list(cache.iterdir())


async def test_mix_failure_fails_the_job_and_keeps_old_output(html_env: HtmlEnv) -> None:
    output = html_env.workdir / "output"
    output.mkdir()
    (output / "final.mp4").write_bytes(b"old")
    job_id = await _run(html_env, FakeBackend(mix_error=MixError("混音失败：no space")))

    job = _job(html_env, job_id)
    assert job.status == "failed" and "混音失败" in (job.error or "")
    assert (output / "final.mp4").read_bytes() == b"old"
    assert not (output / "final.json").exists()


async def test_progress_updates_the_job_and_renews_the_heartbeat(html_env: HtmlEnv) -> None:
    seen: dict[str, Any] = {}

    async def on_video(on_progress: Any) -> None:
        # Make the heartbeat stale, then report half-way: both must be refreshed.
        job = next(iter(_running_jobs(html_env)))
        _backdate(html_env.engine, job, 500)
        reported = on_progress(50, 100)
        if inspect.isawaitable(reported):
            await reported
        row = get_job(html_env.engine, job)
        assert row is not None
        seen["progress"] = row.progress
        assert row.heartbeat_at is not None
        seen["age"] = (datetime.now(UTC) - _aware(row.heartbeat_at)).total_seconds()

    job_id = await _run(html_env, FakeBackend(on_video=on_video))
    assert _job(html_env, job_id).status == "done"
    assert 0.3 < seen["progress"] < 0.7
    assert seen["age"] < 60


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _running_jobs(env: HtmlEnv) -> list[str]:
    with session_scope(env.engine) as db:
        return [row.id for row in db.query(Job).filter(Job.status == "running")]


def _backdate(engine: Engine, job_id: str, seconds: float) -> None:
    with session_scope(engine) as db:
        row = db.get(Job, job_id)
        assert row is not None
        row.heartbeat_at = datetime.now(UTC) - timedelta(seconds=seconds)


@pytest.mark.parametrize("failing", ["video", "mix"])
async def test_unexpected_errors_fail_the_job_instead_of_killing_the_worker(
    html_env: HtmlEnv, failing: str
) -> None:
    """Playwright/ffmpeg/disk problems are not among the named render errors; they must not leave
    the job `running` forever (TD-35 would keep returning it and every later render would stall)."""
    backend = FakeBackend(
        video_error=RuntimeError("playwright exploded") if failing == "video" else None,
        mix_error=FileNotFoundError("ffmpeg") if failing == "mix" else None,
    )
    job_id = await _run(html_env, backend)
    job = _job(html_env, job_id)
    assert job.status == "failed"
    assert job.error is not None and "内部错误" in job.error


async def test_page_edited_during_the_render_is_not_cached_under_the_old_key(
    html_env: HtmlEnv,
) -> None:
    async def edit_while_rendering(_on_progress: Any) -> None:
        (html_env.workdir / "animation/scenes/s-hook.js").write_text(fx.PURE_SCENE_PLAIN + "// B\n")

    backend = FakeBackend(on_video=edit_while_rendering)
    await _run(html_env, backend)
    page = backend.video_calls[0]["page"]
    # The page handed to the renderer is the one assembled before the edit, and so is the cache key.
    assert "// B" not in page.scripts["animation/scenes/s-hook.js"]
    (html_env.workdir / "animation/scenes/s-hook.js").write_text(fx.PURE_SCENE_PLAIN)
    await _run(html_env, backend)
    assert len(backend.video_calls) == 1  # back to content A: A's frames come from the cache


@pytest.mark.parametrize(
    "patch",
    [
        {"narration": False, "music_source": "synth"},
        {"narration": True, "music_source": "synth"},
    ],
    ids=["reel", "explainer-with-music"],
)
async def test_projects_with_music_fail_clearly_until_the_music_mix_exists(
    html_env: HtmlEnv, patch: dict[str, Any]
) -> None:
    from studio.db.repo.projects import update_project_settings

    update_project_settings(html_env.engine, html_env.project_id, patch)
    backend = FakeBackend()
    job_id = await _run(html_env, backend)
    job = _job(html_env, job_id)
    assert job.status == "failed"
    assert job.error is not None and "尚未实现" in job.error
    assert backend.video_calls == [] and backend.mix_calls == []
