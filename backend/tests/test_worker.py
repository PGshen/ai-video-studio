"""`studio.worker` 主循环（M2 T5）。

渲染类用例（真起 manim/ffmpeg 子进程）标 `@pytest.mark.slow`；不依赖真实渲染
的用例（空队列、心跳过期回收、缓存命中跳过重渲染）留在默认范围内，跑得快。
"""

from __future__ import annotations

import json
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
    RenderResult,
    RenderResultWithBytes,
    SceneInput,
)
from studio.jobs import claim_next, create_job, get_job
from studio.worker import _cache_key, _render_and_cache, _ScenePlan, _with_ticks, run_once


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

    def __init__(self, *, fail_with: str | None = None) -> None:
        self.calls: list[RenderRequest] = []
        self._fail_with = fail_with

    async def validate_code(self, scenes: list[SceneInput]) -> tuple[bool, str]:
        return True, ""

    async def render_preview(self, request: PreviewRequest) -> PreviewResult:
        raise NotImplementedError

    async def health_check(self) -> bool:
        return True

    async def render(self, request: RenderRequest, work_dir: str | None = None) -> RenderResult:
        self.calls.append(request)
        if self._fail_with is not None:
            return RenderResult(
                success=False,
                output_path=None,
                duration_seconds=None,
                error_message=self._fail_with,
                render_log=self._fail_with,
            )
        return RenderResultWithBytes(
            success=True,
            output_path="/dev/null",
            duration_seconds=1.0,
            error_message=None,
            render_log="",
            video_bytes=b"fake-mp4-bytes",
        )


def _plan(
    scene_id: str,
    *,
    index: int = 0,
    code: str = "self.add(Dot())",
    audio_hash: str = "sha256:aaa",
    duration: float = 1.0,
) -> _ScenePlan:
    return _ScenePlan(
        scene_id=scene_id,
        scene_index=index,
        code=code,
        narration="",
        description="",
        audio_path=Path(f"/tmp/{scene_id}.wav"),
        audio_hash=audio_hash,
        duration_seconds=duration,
    )


class TestCacheKey:
    def test_cache_key_depends_on_code_audio_and_order(self) -> None:
        base = [_plan("s-a"), _plan("s-b", index=1, code="self.add(Circle())")]

        assert _cache_key(base) == _cache_key(base)  # 确定性
        changed_code = [_plan("s-a", code="self.add(Square())"), base[1]]
        changed_audio = [base[0], _plan("s-b", index=1, audio_hash="sha256:bbb")]
        reordered = [base[1], base[0]]
        assert len({_cache_key(base), _cache_key(changed_code)}) == 2
        assert _cache_key(base) != _cache_key(changed_audio)
        assert _cache_key(base) != _cache_key(reordered)

    def test_changing_an_earlier_scene_invalidates_cache_of_the_whole_render(self) -> None:
        # 镜头间元素会跨镜头延续，前面镜头的改动会影响后面镜头的画面，
        # 所以不能只按单个镜头缓存。
        later = _plan("s-b", index=1, code="self.play(FadeOut(self.dot))")
        before = _cache_key([_plan("s-a", code="self.dot = Dot()"), later])
        after = _cache_key([_plan("s-a", code="self.dot = Square()"), later])
        assert before != after


class TestRunOnceOutput:
    async def test_final_video_is_the_rendered_video_without_subtitle_burn_in(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        # 成片不叠字幕：输出就是渲染结果本身（假引擎返回的不是合法视频，
        # 任何 ffmpeg 后处理都会失败）。
        _write_scene_codes(animation_project.workdir, _SCENE_CODES)
        job = create_job(
            animation_project.engine,
            type="final_render",
            project_id=animation_project.project_id,
            payload={},
        )

        await run_once(
            animation_project.engine,
            animation_project.blobs,
            data_dir=animation_project.data_dir,
            render_engine=_FakeRenderEngine(),
        )

        done = get_job(animation_project.engine, job.id)
        assert done is not None
        assert done.status == "done", done.error
        final_video = animation_project.workdir / "output" / "final.mp4"
        assert final_video.read_bytes() == b"fake-mp4-bytes"


class TestWithTicks:
    async def test_ticks_while_waiting_and_returns_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        monkeypatch.setattr("studio.worker._TICK_INTERVAL_SECONDS", 0.01)
        ticks: list[int] = []

        async def slow() -> str:
            await asyncio.sleep(0.08)
            return "done"

        result = await _with_ticks(slow(), lambda: ticks.append(1))

        assert result == "done"
        assert len(ticks) >= 2  # 等待期间持续续心跳


class TestRenderAndCache:
    async def test_all_scenes_are_rendered_together_in_one_request(self, tmp_path: Path) -> None:
        # 回归：逐镜头单独渲染时，后面镜头引用前面镜头的 `self.xxx` 会 AttributeError。
        workdir = tmp_path / "project"
        workdir.mkdir()
        plans = [_plan("s-a"), _plan("s-b", index=1), _plan("s-c", index=2)]

        fake_engine = _FakeRenderEngine()
        await _render_and_cache(
            fake_engine, workdir, plans, resolution=(480, 270), fps=15, on_tick=lambda: None
        )

        assert len(fake_engine.calls) == 1
        request = fake_engine.calls[0]
        assert [s.scene_index for s in request.scenes] == [0, 1, 2]
        assert [s.audio.scene_index for s in request.scenes if s.audio] == [0, 1, 2]

    async def test_second_call_with_same_plans_skips_rerender(self, tmp_path: Path) -> None:
        workdir = tmp_path / "project"
        workdir.mkdir()
        plans = [_plan("s-a", duration=2.0), _plan("s-b", index=1, duration=3.0)]

        fake_engine = _FakeRenderEngine()
        first = await _render_and_cache(
            fake_engine, workdir, plans, resolution=(480, 270), fps=15, on_tick=lambda: None
        )
        second = await _render_and_cache(
            fake_engine, workdir, plans, resolution=(480, 270), fps=15, on_tick=lambda: None
        )

        assert first == second
        assert first.read_bytes() == b"fake-mp4-bytes"
        assert len(fake_engine.calls) == 1  # 第二次命中缓存，没有再调用 render()

    async def test_failure_names_the_scene_even_when_rich_wraps_the_frame(
        self, tmp_path: Path
    ) -> None:
        from studio.worker import WorkerRenderError

        workdir = tmp_path / "project"
        workdir.mkdir()
        plans = [_plan("s-a"), _plan("s-b", index=1)]
        fake_engine = _FakeRenderEngine(
            fail_with="│ /tmp/x/scene.py:29 in │\n│ _scene_1 │\nAttributeError: x"
        )

        with pytest.raises(WorkerRenderError, match="s-b"):
            await _render_and_cache(
                fake_engine, workdir, plans, resolution=(480, 270), fps=15, on_tick=lambda: None
            )

    async def test_failure_names_the_scene_from_traceback(self, tmp_path: Path) -> None:
        from studio.worker import WorkerRenderError

        workdir = tmp_path / "project"
        workdir.mkdir()
        plans = [_plan("s-a"), _plan("s-b", index=1)]
        fake_engine = _FakeRenderEngine(
            fail_with="Manim exited with code 1\n│ scene.py:29 in _scene_1 │\nAttributeError: x"
        )

        with pytest.raises(WorkerRenderError, match="s-b"):
            await _render_and_cache(
                fake_engine, workdir, plans, resolution=(480, 270), fps=15, on_tick=lambda: None
            )


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

    async def test_scenes_can_share_state_through_self_attributes(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        # 回归：镜头 2 引用镜头 1 里 `self.dot` 定义的元素（跨镜头延续是设计内的写法）。
        _write_scene_codes(
            animation_project.workdir,
            {
                "s-hook": "self.dot = Dot()\nself.add(self.dot)",
                "s-explain": "self.play(self.dot.animate.set_color(RED), run_time=0.2)",
            },
        )
        job = create_job(
            animation_project.engine,
            type="final_render",
            project_id=animation_project.project_id,
            payload={},
        )

        await run_once(
            animation_project.engine, animation_project.blobs, data_dir=animation_project.data_dir
        )

        done = get_job(animation_project.engine, job.id)
        assert done is not None
        assert done.status == "done", done.error

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
        assert len(cached_files_after_first_run) == 1  # 整条成片只渲染一次，一份缓存
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
