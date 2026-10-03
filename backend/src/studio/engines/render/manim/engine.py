"""`RenderEngine` 协议的 manim 实现：拼脚本（`script.py`）+ 起子进程（`process.py`）。"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time

from studio.config import get_settings
from studio.engines.render.base import (
    PreviewKeyframe,
    PreviewRequest,
    PreviewResult,
    RenderRequest,
    RenderResult,
    SceneInput,
)
from studio.engines.render.manim.keyframes import extract_keyframe, probe_duration_seconds
from studio.engines.render.manim.process import run_dry_run, run_render
from studio.engines.render.manim.script import (
    _build_manim_script,
    _signature_check,
    _static_check,
    _undefined_name_check,
)

_PREVIEW_RESOLUTION = (480, 270)
_PREVIEW_FPS = 15
_PREVIEW_TIMEOUT_SECONDS = 120.0
_TIMEOUT_ERROR_MESSAGE = "预览渲染超时"


class ManimRenderEngine:
    engine_name = "manim"

    async def validate_code(self, scenes: list[SceneInput]) -> tuple[bool, str]:
        script = _build_manim_script(scenes, include_audio=False)

        static_errors = _static_check(script)
        if static_errors:
            return False, "\n".join(static_errors)

        undefined_errors = _undefined_name_check(script)
        if undefined_errors:
            return False, "\n".join(undefined_errors)

        signature_errors = _signature_check(script)
        if signature_errors:
            return False, "\n".join(signature_errors)

        return await run_dry_run(script)

    async def render(self, request: RenderRequest, work_dir: str | None = None) -> RenderResult:
        script = _build_manim_script(
            request.scenes, resolution=request.resolution, emit_scene_markers=True
        )
        settings = get_settings()
        return await run_render(
            script,
            resolution=request.resolution,
            fps=request.fps,
            # 所有镜头在同一次渲染里跑完，超时按镜头数放大。
            timeout_seconds=settings.manim_timeout_seconds * max(len(request.scenes), 1),
            work_dir=work_dir,
        )

    async def render_preview(
        self, request: PreviewRequest, timeout_seconds: float = _PREVIEW_TIMEOUT_SECONDS
    ) -> PreviewResult:
        script = _build_manim_script(request.scenes, resolution=_PREVIEW_RESOLUTION)

        start = time.monotonic()
        with tempfile.TemporaryDirectory() as tmpdir:
            render_result = await run_render(
                script,
                resolution=_PREVIEW_RESOLUTION,
                fps=_PREVIEW_FPS,
                timeout_seconds=timeout_seconds,
                work_dir=tmpdir,
            )
            render_duration = time.monotonic() - start

            if not render_result.success:
                error_message = render_result.error_message or ""
                if "timed out" in error_message:
                    error_message = _TIMEOUT_ERROR_MESSAGE
                return PreviewResult(
                    success=False,
                    error_message=error_message,
                    render_duration_seconds=render_duration,
                    duration_deviation_seconds=None,
                    keyframes=[],
                    render_log=render_result.render_log,
                )

            assert render_result.output_path is not None  # success 时 render() 保证有输出路径

            start_offset = sum(
                scene.audio.duration_seconds
                for scene in request.scenes
                if scene.audio is not None and scene.scene_index < request.target_scene_index
            )

            # ffmpeg 的 -frames:v 1 找的是"第一个 PTS >= 目标时刻"的帧；最后一帧的
            # PTS 是 (nb_frames-1)/fps，比 ffprobe 报的视频时长（nb_frames/fps）少
            # 整整一帧，seek 到时长本身或只留半帧余量都会落在最后一帧之后抽不到东
            # 西，所以要留满一帧的安全边界。
            total_duration = await probe_duration_seconds(render_result.output_path)
            safe_upper_bound = max(total_duration - (1.0 / _PREVIEW_FPS), 0.0)

            keyframes = [
                PreviewKeyframe(
                    beat_index=beat_index,
                    png_bytes=await extract_keyframe(
                        render_result.output_path,
                        min(start_offset + beat_end_time, safe_upper_bound),
                    ),
                )
                for beat_index, beat_end_time in enumerate(request.beat_end_times)
            ]

            duration_deviation_seconds = None
            if request.audio_duration_seconds is not None:
                target_duration = total_duration - start_offset
                duration_deviation_seconds = target_duration - request.audio_duration_seconds

            return PreviewResult(
                success=True,
                error_message=None,
                render_duration_seconds=render_duration,
                duration_deviation_seconds=duration_deviation_seconds,
                keyframes=keyframes,
                render_log=render_result.render_log,
            )

    async def health_check(self) -> bool:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "manim",
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
