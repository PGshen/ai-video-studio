"""用 ffmpeg 从渲染好的预览视频里按时间点抽取关键帧图片，并探测视频总时长。"""

from __future__ import annotations

import asyncio


class KeyframeExtractionError(RuntimeError):
    """ffmpeg/ffprobe 子进程失败。"""


async def extract_keyframe(video_path: str, at_seconds: float) -> bytes:
    """在 `at_seconds` 处抽取一帧，返回 PNG 字节。

    `-ss` 放在 `-i` 之后（输出侧寻址）而不是之前：预览视频很短（往往不到一秒），
    容器关键帧间隔粗糙的"快速寻址"经常直接跳过实际内容，逐帧解码到目标时刻更
    可靠，短视频这点解码开销可以忽略。
    """
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-i",
        video_path,
        "-ss",
        f"{max(at_seconds, 0.0):.3f}",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0 or not stdout:
        raise KeyframeExtractionError(
            f"ffmpeg 抽帧失败（t={at_seconds:.3f}s）：{stderr.decode(errors='replace')[-1000:]}"
        )
    return stdout


async def probe_duration_seconds(video_path: str) -> float:
    """用 ffprobe 读取视频画面轨的时长（秒）。

    特意选视频流（`-select_streams v:0`）而不是容器整体（`format=duration`）：
    manim 的 `add_sound()` 会给音轨套一层至少 1 秒的静音底轨（docs/references/
    manim.md），容器时长会被音轨拖长，用它算镜头起止时间会算错。
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise KeyframeExtractionError(
            f"ffprobe 探测时长失败：{stderr.decode(errors='replace')[-1000:]}"
        )
    return float(stdout.decode().strip())
