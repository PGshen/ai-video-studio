"""逐帧出图并编码成无声 MP4（设计 §5.5）。

第 i 帧取时刻 `i / fps`，帧数 `ceil(duration × fps)`；帧用 `page.render_jpeg`（与预览、
probe 共用同一个渲染器）取出，经 `image2pipe` 交给 ffmpeg（libx264、yuv420p、CRF 15）。
输出先写同目录的临时文件，成功后原子改名：任何失败或取消都会终止 ffmpeg、删掉临时文件，
已有的输出文件保持不变。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import math
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from studio import fsretry, proc
from studio.engines.render.html.browser import PageLike

FFMPEG = "ffmpeg"
_STDERR_TAIL_LINES = 12
_FRAME_EPSILON = 1e-6

ProgressCallback = Callable[[int, int], Awaitable[None] | None]


class VideoRenderError(RuntimeError):
    """成片出帧失败；消息点名帧序号与时刻，原始异常（含镜头 id 与堆栈）作为 `__cause__`。"""


class VideoEncodeError(VideoRenderError):
    """ffmpeg 编码失败或提前退出；消息带 stderr 末尾若干行。"""


@dataclass(frozen=True, slots=True)
class VideoStats:
    frames: int
    seconds: float
    """出帧加编码的墙钟耗时。"""


def frame_count(duration: float, fps: int) -> int:
    return max(1, math.ceil(duration * fps - _FRAME_EPSILON))


def frame_time(index: int, fps: int) -> float:
    return index / fps


def encode_signature(fps: int) -> list[str]:
    """Every ffmpeg argument except the output path: what decides the encoded bytes. The cache key
    of the silent video includes it, so changing a codec setting here invalidates old caches."""
    return [
        FFMPEG,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "image2pipe",
        "-framerate",
        str(fps),
        "-c:v",
        "mjpeg",
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-crf",
        "15",
        "-vf",
        "scale=in_range=pc:out_range=tv,format=yuv420p",
        "-r",
        str(fps),
    ]


def build_encode_command(output: Path, fps: int) -> list[str]:
    return [*encode_signature(fps), str(output)]


async def _notify(callback: ProgressCallback | None, done: int, total: int) -> None:
    if callback is None:
        return
    result = callback(done, total)
    if inspect.isawaitable(result):
        await result


def _tail(stderr: bytes) -> str:
    return "\n".join(stderr.decode(errors="replace").strip().splitlines()[-_STDERR_TAIL_LINES:])


async def render_silent_video(
    page: PageLike,
    duration: float,
    output: Path,
    *,
    fps: int = 30,
    on_progress: ProgressCallback | None = None,
) -> VideoStats:
    started = time.monotonic()
    total = frame_count(duration, fps)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(f"{output.stem}.tmp{output.suffix}")
    process = await asyncio.create_subprocess_exec(
        *build_encode_command(temp, fps),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        env=proc.child_env(os.environ),
        **proc.spawn_kwargs(),
    )
    assert process.stdin is not None and process.stderr is not None
    stderr_reader = asyncio.ensure_future(process.stderr.read())
    try:
        for index in range(total):
            t = frame_time(index, fps)
            try:
                jpeg = await page.render_jpeg(t)
            except Exception as exc:
                raise VideoRenderError(f"第 {index} 帧（t={t:.3f}s）渲染失败：{exc}") from exc
            try:
                process.stdin.write(jpeg)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                await process.wait()
                raise VideoEncodeError(
                    f"ffmpeg 在第 {index} 帧提前退出：{_tail(await stderr_reader)}"
                ) from exc
            await _notify(on_progress, index + 1, total)
        process.stdin.close()
        await process.wait()
        stderr = await stderr_reader
        if process.returncode != 0:
            raise VideoEncodeError(
                f"ffmpeg 编码失败（退出码 {process.returncode}）：{_tail(stderr)}"
            )
        fsretry.replace(temp, output)  # the player may still be reading the old file
    except BaseException:
        proc.kill_proc_tree(process)  # sync: an await here could be cancelled again
        with contextlib.suppress(Exception):
            await process.wait()
        stderr_reader.cancel()
        temp.unlink(missing_ok=True)
        raise
    return VideoStats(frames=total, seconds=time.monotonic() - started)
