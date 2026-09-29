"""`studio.worker` 主循环（M2 T5）。

渲染类用例（真起 manim/ffmpeg 子进程）标 `@pytest.mark.slow`；不依赖真实渲染
的用例（空队列、心跳过期回收、缓存命中跳过重渲染）留在默认范围内，跑得快。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine

from conftest import AnimationProjectEnv
from studio.db.engine import session_scope
from studio.db.models import Job
from studio.engines.render.base import (
    PreviewRequest,
    PreviewResult,
    RenderRequest,
    RenderResultWithBytes,
    SceneInput,
)
from studio.jobs import claim_next, create_job, get_job
from studio.worker import _cache_key, _ScenePlan, run_once


def _backdate_heartbeat(engine: Engine, job_id: str, seconds_ago: float) -> None:
    with session_scope(engine) as db:
        row = db.get(Job, job_id)
        assert row is not None
        row.heartbeat_at = datetime.now(UTC) - timedelta(seconds=seconds_ago)


def _write_scene_codes(workdir: Path, codes: dict[str, str]) -> None:
    scenes_dir = workdir / "animation" / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    for scene_id, code in codes.items():
        (scenes_dir / f"{scene_id}.py").write_text(code, encoding="utf-8")


class TestRunOnceQueueHandling:
    async def test_returns_false_when_queue_is_empty(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        claimed = await run_once(
            animation_project.engine, animation_project.blobs, data_dir=animation_project.data_dir
        )

        assert claimed is False

    async def test_reaps_stale_running_job_before_claiming_next(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        stale = create_job(
            animation_project.engine,
            type="final_render",
            project_id=animation_project.project_id,
            payload={},
        )
        # 让 stale 先被别的 worker "领走"（进入 running），心跳再过期。
        claim_next(animation_project.engine, type="final_render")
        _backdate_heartbeat(animation_project.engine, stale.id, seconds_ago=999)

        # 队列里此刻没有 queued 任务，run_once 应该先 reap 掉 stale，再发现队列空。
        claimed = await run_once(
            animation_project.engine, animation_project.blobs, data_dir=animation_project.data_dir
        )

        assert claimed is False
        reaped = get_job(animation_project.engine, stale.id)
        assert reaped is not None
        assert reaped.status == "failed"


class TestRunOnceSceneDataValidation:
    async def test_fails_job_when_animation_scene_code_is_missing(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        # 不写任何 animation/scenes/*.py，直接创建任务。
        job = create_job(
            animation_project.engine,
            type="final_render",
            project_id=animation_project.project_id,
            payload={},
        )

        claimed = await run_once(
            animation_project.engine, animation_project.blobs, data_dir=animation_project.data_dir
        )

        assert claimed is True
        failed = get_job(animation_project.engine, job.id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error is not None
        assert "s-hook" in failed.error


class _FakeRenderEngine:
    """不真起 manim 子进程；用来单独验证缓存命中/未命中的调用次数。

    完整实现 `RenderEngine` 协议（哪怕用不到 `validate_code`/`render_preview`/
    `health_check`），这样才能作为 `_render_and_cache_scene` 的 `render_engine`
    参数通过 pyright 的结构类型检查。
    """

    engine_name = "fake"

    def __init__(self) -> None:
        self.calls: list[RenderRequest] = []

    async def validate_code(self, scenes: list[SceneInput]) -> tuple[bool, str]:
        return True, ""

    async def render_preview(self, request: PreviewRequest) -> PreviewResult:
        raise NotImplementedError

    async def health_check(self) -> bool:
        return True

    async def render(
        self, request: RenderRequest, work_dir: str | None = None
    ) -> RenderResultWithBytes:
        self.calls.append(request)
        return RenderResultWithBytes(
            success=True,
            output_path="/dev/null",
            duration_seconds=1.0,
            error_message=None,
            render_log="",
            video_bytes=b"fake-mp4-bytes",
        )


@dataclass
class _StubPlan:
    code: str
    audio_hash: str


class TestCacheKey:
    def test_cache_key_depends_on_code_and_audio_hash(self) -> None:
        plan_a = _ScenePlan(
            scene_id="s-a",
            scene_index=0,
            code="self.add(Dot())",
            narration="",
            description="",
            audio_path=Path("/tmp/a.wav"),
            audio_hash="sha256:aaa",
            duration_seconds=1.0,
        )
        plan_b = _ScenePlan(
            scene_id="s-a",
            scene_index=0,
            code="self.add(Square())",  # 代码不同
            narration="",
            description="",
            audio_path=Path("/tmp/a.wav"),
            audio_hash="sha256:aaa",
            duration_seconds=1.0,
        )
        plan_c = _ScenePlan(
            scene_id="s-a",
            scene_index=0,
            code="self.add(Dot())",
            narration="",
            description="",
            audio_path=Path("/tmp/a.wav"),
            audio_hash="sha256:bbb",  # 音频不同
            duration_seconds=1.0,
        )

        assert _cache_key(plan_a) == _cache_key(plan_a)  # 确定性
        assert _cache_key(plan_a) != _cache_key(plan_b)
        assert _cache_key(plan_a) != _cache_key(plan_c)


class TestRenderAndCacheScene:
    async def test_second_call_with_same_plan_skips_rerender(self, tmp_path: Path) -> None:
        from studio.worker import _render_and_cache_scene

        workdir = tmp_path / "project"
        workdir.mkdir()
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"RIFF....")

        plan = _ScenePlan(
            scene_id="s-hook",
            scene_index=0,
            code="self.add(Dot())",
            narration="旁白",
            description="",
            audio_path=audio_path,
            audio_hash="sha256:test",
            duration_seconds=1.0,
        )

        fake_engine = _FakeRenderEngine()
        first_path = await _render_and_cache_scene(
            fake_engine, workdir, plan, resolution=(480, 270), fps=15
        )
        second_path = await _render_and_cache_scene(
            fake_engine, workdir, plan, resolution=(480, 270), fps=15
        )

        assert first_path == second_path
        assert first_path.read_bytes() == b"fake-mp4-bytes"
        assert len(fake_engine.calls) == 1  # 第二次命中缓存，没有再调用 render()


# ---------------------------------------------------------------------------
# 慢测试：真起 manim/ffmpeg 子进程，覆盖端到端渲染成片的主路径。
# ---------------------------------------------------------------------------

_SCENE_CODES = {
    "s-hook": "self.add(Dot())",
    "s-explain": "self.add(Square())",
}


@pytest.mark.slow
class TestRunOnceRendersFinalVideo:
    async def test_produces_final_mp4_and_json_and_marks_job_done(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        _write_scene_codes(animation_project.workdir, _SCENE_CODES)
        job = create_job(
            animation_project.engine,
            type="final_render",
            project_id=animation_project.project_id,
            payload={},
        )

        claimed = await run_once(
            animation_project.engine, animation_project.blobs, data_dir=animation_project.data_dir
        )

        assert claimed is True
        done = get_job(animation_project.engine, job.id)
        assert done is not None
        assert done.status == "done", done.error

        final_video = animation_project.workdir / "output" / "final.mp4"
        final_meta_path = animation_project.workdir / "output" / "final.json"
        assert final_video.is_file()
        assert final_video.stat().st_size > 0
        assert final_meta_path.is_file()

        final_meta = json.loads(final_meta_path.read_text(encoding="utf-8"))
        assert final_meta["snapshot_id"]
        assert set(final_meta["scene_hashes"]) == {"s-hook", "s-explain"}
        assert final_meta["rendered_at"]

    async def test_reruns_use_render_cache(self, animation_project: AnimationProjectEnv) -> None:
        _write_scene_codes(animation_project.workdir, _SCENE_CODES)
        first_job = create_job(
            animation_project.engine,
            type="final_render",
            project_id=animation_project.project_id,
            payload={},
        )
        await run_once(
            animation_project.engine, animation_project.blobs, data_dir=animation_project.data_dir
        )
        first_done = get_job(animation_project.engine, first_job.id)
        assert first_done is not None and first_done.status == "done"

        cache_dir = animation_project.workdir / ".cache" / "render_cache"
        cached_files_after_first_run = sorted(
            p for p in cache_dir.glob("*.mp4") if p.name != "concat_output.mp4"
        )
        assert len(cached_files_after_first_run) == 2  # 两个镜头各一份缓存
        mtimes_after_first_run = {p: p.stat().st_mtime_ns for p in cached_files_after_first_run}

        second_job = create_job(
            animation_project.engine,
            type="final_render",
            project_id=animation_project.project_id,
            payload={},
        )
        claimed_again = await run_once(
            animation_project.engine, animation_project.blobs, data_dir=animation_project.data_dir
        )

        assert claimed_again is True
        second_done = get_job(animation_project.engine, second_job.id)
        assert second_done is not None and second_done.status == "done"
        # 缓存文件没有被重新写过（mtime 不变），证明第二轮跳过了重渲染。
        for path, mtime in mtimes_after_first_run.items():
            assert path.stat().st_mtime_ns == mtime

    async def test_fails_job_with_scene_id_when_one_scene_has_broken_code(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        broken_codes = {
            "s-hook": "self.add(Dot())",
            "s-explain": "self.add(TotallyUndefinedManimThing())",
        }
        _write_scene_codes(animation_project.workdir, broken_codes)
        job = create_job(
            animation_project.engine,
            type="final_render",
            project_id=animation_project.project_id,
            payload={},
        )

        claimed = await run_once(
            animation_project.engine, animation_project.blobs, data_dir=animation_project.data_dir
        )

        assert claimed is True
        failed = get_job(animation_project.engine, job.id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error is not None
        assert "s-explain" in failed.error
