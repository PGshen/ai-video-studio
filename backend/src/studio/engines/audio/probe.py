"""用 `ffprobe` 确认上传的文件是音频并读出时长（子项目 4B 设计 §3.1）。

纯能力层，只依赖标准库。不信任文件名与扩展名：只看 ffprobe 对内容的判断。
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from pathlib import Path


class AudioProbeError(ValueError):
    """文件不是可用的音频；消息是给用户看的中文原因。"""


@dataclass(frozen=True, slots=True)
class AudioProbe:
    duration: float
    codec: str


async def probe_audio(path: Path, *, timeout: float = 15.0) -> AudioProbe:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name:format=duration",
        "-of", "json", str(path),
    ]  # fmt: skip
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise AudioProbeError(f"无法运行 ffprobe：{exc}") from exc
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise AudioProbeError(f"音频探测超时（{timeout:g} 秒）") from exc
    if proc.returncode != 0:
        detail = stderr.decode(errors="replace").strip()[-200:]
        raise AudioProbeError(f"不是可识别的音频文件：{detail}")
    try:
        info = json.loads(stdout)
        streams = info.get("streams") or []
        duration = float(info["format"]["duration"])
    except (ValueError, KeyError, TypeError) as exc:
        raise AudioProbeError("无法读出音频时长，文件可能不是音频") from exc
    if not streams:
        raise AudioProbeError("文件里没有音频流")
    if not math.isfinite(duration) or duration <= 0:
        raise AudioProbeError("音频时长无效")
    return AudioProbe(duration=duration, codec=str(streams[0].get("codec_name", "")))
