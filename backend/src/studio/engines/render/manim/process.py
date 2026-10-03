"""Manim 子进程执行：dry-run 静态校验、全画质渲染、日志清理与镜头号定位。

从 `../ai-video/backend/app/engines/render/manim.py` 迁移（原单文件按职责拆分，
决策记录 D1），脚本构建/静态分析在 `script.py`，本文件只负责“已经拼好的脚本”
如何跑起来：起子进程、清理输出、把 traceback 定位回具体镜头号。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

from studio.engines.render.base import RenderResult, RenderResultWithBytes

logger = logging.getLogger(__name__)

_PROGRESS_BAR_RE = re.compile(r"\d+%\|")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# rich 的 traceback 面板会在固定宽度处折行，`in _scene_N` 可能被拆成
# `in │\n│ _scene_N`，所以 `in` 与函数名之间容忍空白和边框字符。
_TRACEBACK_SCENE_RE = re.compile(r"\bin[\s│]+_scene_(\d+)\b")

# Runs the scene directly instead of going through `manim render`, because the
# CLI catches exceptions with a rich pretty-printed panel (`error_console.
# print_exception()`) that wraps to a fixed width and buries the actual
# exception type/message dozens of lines into a boxed traceback — useless
# once truncated for logging. A plain `traceback.print_exc()` keeps the
# exception type and message on the last line, always.
_DRY_RUN_DRIVER = """
import sys
import traceback

from manim import config

config.dry_run = True
config.disable_caching = True

sys.path.insert(0, {tmpdir!r})

try:
    from scene import MainScene
    MainScene().render()
except Exception:
    traceback.print_exc()
    sys.exit(1)
sys.exit(0)
"""

_DRY_RUN_TIMEOUT_SECONDS = 120


def failed_scene_index(log: str) -> int | None:
    """渲染/校验日志里 traceback 最内层 `_scene_N` 帧对应的镜头序号（没有则 `None`）。"""
    matches = _TRACEBACK_SCENE_RE.findall(log)
    return int(matches[-1]) if matches else None


@contextlib.contextmanager
def _tmpdir_context(work_dir: str | None):
    if work_dir is not None:
        yield work_dir
    else:
        with tempfile.TemporaryDirectory() as d:
            yield d


def _find_output_video(tmpdir: str, expected_path: str) -> str | None:
    if os.path.exists(expected_path):
        return expected_path
    for root, _, files in os.walk(tmpdir):
        for fname in files:
            if fname.endswith(".mp4"):
                return os.path.join(root, fname)
    return None


def _filter_dry_run_log(log: str) -> str:
    return "\n".join(
        line
        for line in (
            _ANSI_ESCAPE_RE.sub("", raw_line).strip() for raw_line in re.split(r"[\r\n]", log)
        )
        if line and "Caching disabled" not in line and not _PROGRESS_BAR_RE.search(line)
    )


async def run_dry_run(script: str) -> tuple[bool, str]:
    """Dry-run the assembled script through a subprocess; no video is produced.

    Returns ``(is_valid, message)``. On a runtime error, ``message`` is
    tailed to the exception's type/message line and prefixed with the
    originating scene number when the traceback names one.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = os.path.join(tmpdir, "scene.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)

        driver_path = os.path.join(tmpdir, "_dry_run_driver.py")
        with open(driver_path, "w", encoding="utf-8") as f:
            f.write(_DRY_RUN_DRIVER.format(tmpdir=tmpdir))

        cmd = [sys.executable, driver_path]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=tmpdir,
        )
        try:
            async with asyncio.timeout(_DRY_RUN_TIMEOUT_SECONDS):
                output, _ = await proc.communicate()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return False, f"Dry-run timed out after {_DRY_RUN_TIMEOUT_SECONDS}s"

        log = output.decode(errors="replace")
        if proc.returncode != 0:
            # The exception type/message is on the last lines of a
            # traceback, so tail the log rather than truncating its head.
            filtered_log = _filter_dry_run_log(log)
            logger.info("[ManimValidate] dry_run failed:\n%s", filtered_log[-2000:])
            tail = filtered_log[-2000:]
            # The traceback's innermost `_scene_N` frame (Manim internals
            # called from it don't carry that name) tells us which scene's
            # code actually triggered the exception.
            scene_matches = _TRACEBACK_SCENE_RE.findall(log)
            if scene_matches:
                tail = f"scene {scene_matches[-1]}: {tail}"
            return False, tail

        logger.info("[ManimValidate] dry_run passed")
        return True, ""


async def run_render(
    script: str,
    *,
    resolution: tuple[int, int],
    fps: int,
    timeout_seconds: float,
    work_dir: str | None = None,
) -> RenderResult:
    """Render the assembled script to an mp4 through the ``manim`` CLI."""
    with _tmpdir_context(work_dir) as tmpdir:
        script_path = os.path.join(tmpdir, "scene.py")
        output_path = os.path.join(tmpdir, "output.mp4")

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)

        cmd = [
            sys.executable,
            "-m",
            "manim",
            "render",
            script_path,
            "MainScene",
            "--output_file",
            output_path,
            "--format",
            "mp4",
            "--media_dir",
            tmpdir,
            "--resolution",
            f"{resolution[0]},{resolution[1]}",
            "--fps",
            str(fps),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=tmpdir,
        )

        assert proc.stdout is not None  # guaranteed by stdout=PIPE above

        log_lines: list[str] = []
        try:
            async with asyncio.timeout(timeout_seconds):
                async for raw in proc.stdout:
                    line = raw.decode(errors="replace").rstrip()
                    log_lines.append(line)
                    logger.info("[Manim] %s", line)
                await proc.wait()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            render_log = "\n".join(log_lines)
            return RenderResult(
                success=False,
                output_path=None,
                duration_seconds=None,
                error_message=f"Manim render timed out after {timeout_seconds:.0f}s",
                render_log=render_log,
            )

        render_log = "\n".join(log_lines)

        if proc.returncode != 0:
            return RenderResult(
                success=False,
                output_path=None,
                duration_seconds=None,
                error_message=(
                    f"Manim exited with code {proc.returncode}\n"
                    f"{render_log.strip() if render_log else ''}"
                ),
                render_log=render_log,
            )

        # Manim may place output in a subdirectory; find the mp4.
        actual_output = _find_output_video(tmpdir, output_path)
        if actual_output is None:
            return RenderResult(
                success=False,
                output_path=None,
                duration_seconds=None,
                error_message="Output video file not found after render",
                render_log=render_log,
            )

        video_bytes = Path(actual_output).read_bytes()
        return RenderResultWithBytes(
            success=True,
            output_path=actual_output,
            duration_seconds=None,
            error_message=None,
            render_log=render_log,
            video_bytes=video_bytes,
        )
