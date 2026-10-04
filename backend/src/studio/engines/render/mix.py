"""成片混音（设计 §8 第 6 步）：把无声视频和按时间轴起点摆放的旁白轨合成最终 MP4。

纯能力层：只依赖标准库和系统 ffmpeg，不 import `studio.timeline`——调用方把时间轴上
每个镜头的起点换成 `AudioTrack.start`。输出时长以 `duration` 为准：旁白长了被裁掉，
短了补静音。接口预留背景乐轨（`music`），子项目 3 再加侧链压低。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_SAMPLE_RATE = 44100
_STDERR_TAIL_LINES = 12


class MixError(RuntimeError):
    """ffmpeg 混音失败；消息带 stderr 末尾若干行。"""


@dataclass(frozen=True, slots=True)
class AudioTrack:
    path: Path
    start: float
    """这条轨在成片里的起点（秒）。"""


def _duration_arg(duration: float) -> str:
    return f"{duration:g}"


def build_mix_command(
    video: Path, tracks: Sequence[AudioTrack], duration: float, output: Path
) -> list[str]:
    """ffmpeg 参数（含可执行文件名）。每条旁白轨 `adelay` 到自己的起点，`amix` 不归一化，
    `apad` + `-t` 把总时长钉在 `duration`；没有旁白轨时补一条静音 AAC 轨，成片总有音轨。"""
    head = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video)]
    tail = [
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        "-t",
        _duration_arg(duration),
        str(output),
    ]
    if not tracks:
        return [
            *head,
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={_SAMPLE_RATE}:cl=stereo",
            "-map",
            "0:v",
            "-map",
            "1:a",
            *tail,
        ]
    inputs: list[str] = []
    delayed: list[str] = []
    for index, track in enumerate(tracks):
        inputs += ["-i", str(track.path)]
        millis = round(track.start * 1000)
        delayed.append(f"[{index + 1}:a]adelay={millis}|{millis}[a{index}]")
    labels = "".join(f"[a{index}]" for index in range(len(tracks)))
    graph = (
        ";".join(delayed)
        + f";{labels}amix=inputs={len(tracks)}:normalize=0:duration=longest,apad[aout]"
    )
    return [*head, *inputs, "-filter_complex", graph, "-map", "0:v", "-map", "[aout]", *tail]


async def mix_final(
    video: Path,
    tracks: Sequence[AudioTrack],
    duration: float,
    output: Path,
    *,
    music: AudioTrack | None = None,
) -> None:
    """混音并写到 `output`；先写同目录的临时文件，成功后原子改名，失败不留半成品。"""
    if music is not None:
        raise NotImplementedError("背景乐轨留给子项目 3")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(f"{output.stem}.tmp{output.suffix}")
    command = build_mix_command(video, tracks, duration, temp)
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, stderr = await process.communicate()
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        temp.unlink(missing_ok=True)
        raise
    if process.returncode != 0:
        temp.unlink(missing_ok=True)
        tail = "\n".join(stderr.decode(errors="replace").strip().splitlines()[-_STDERR_TAIL_LINES:])
        raise MixError(f"混音失败（ffmpeg 退出码 {process.returncode}）：{tail}")
    temp.replace(output)
