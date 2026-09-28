"""`RenderEngine` 协议的 manim 实现：拼脚本（`script.py`）+ 起子进程（`process.py`）。"""

from __future__ import annotations

import asyncio
import sys

from studio.config import get_settings
from studio.engines.render.base import (
    PreviewRequest,
    PreviewResult,
    RenderRequest,
    RenderResult,
    SceneInput,
)
from studio.engines.render.manim.process import run_dry_run, run_render
from studio.engines.render.manim.script import (
    _build_manim_script,
    _signature_check,
    _static_check,
    _undefined_name_check,
)


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
        script = _build_manim_script(request.scenes, resolution=request.resolution)
        settings = get_settings()
        return await run_render(
            script,
            resolution=request.resolution,
            fps=request.fps,
            timeout_seconds=settings.manim_timeout_seconds,
            work_dir=work_dir,
        )

    async def render_preview(self, request: PreviewRequest) -> PreviewResult:
        raise NotImplementedError("render_preview 由 M2 T2 实现")

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
