"""成片混音（设计 §8 第 6 步）：把无声视频和按时间轴起点摆放的旁白轨合成最终 MP4。

纯能力层：只依赖标准库和系统 ffmpeg，不 import `studio.timeline`——调用方把时间轴上
每个镜头的起点换成 `AudioTrack.start`。输出时长以 `duration` 为准：旁白长了被裁掉，
短了补静音。背景乐轨（`music`）：只有配乐时直接铺满；有旁白时可以用旁白总线做侧链把配乐压低。
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
    max_seconds: float | None = None
    """最多播多久（旁白轨传镜头时长）：配音比镜头长时不能叠进下一个镜头。"""
    gain_db: float = 0.0
    """这条轨的增益（dB）；背景乐用它压低音量，旁白轨不用。"""


@dataclass(frozen=True, slots=True)
class MusicMix:
    """背景乐轨：`track.start` 恒为 0（配乐从成片开头起放）。"""

    track: AudioTrack
    duck_under_narration: bool = False
    fade_in: float = 0.015
    fade_out: float = 0.015
    """首尾淡变（秒）。默认 15 ms 只防爆音；讲解背景乐用 1 秒与 1.5 秒。"""


BED_GAIN_DB = -8.0
BED_FADE_IN = 1.0
BED_FADE_OUT = 1.5
"""讲解背景乐的默认混音：压低 8 dB、首淡入 1 秒、尾淡出 1.5 秒（设计 §8.1）；
成片（worker）与实时预览（api 的 `gain`）共用，保证听到的一致。"""

# 侧链压低参数（实测定值见 docs/references/ffmpeg.md「侧链压低」）。
_DUCK = "threshold=0.03:ratio=6:attack=10:release=400:makeup=1"


def _duration_arg(duration: float) -> str:
    return f"{duration:g}"


def _music_chain(music: MusicMix, input_index: int, duration: float, label: str) -> str:
    """配乐 → 44.1 kHz 立体声 → 增益 → 裁到总长 → 淡入淡出 → 补静音到总长（两端都有限）。"""
    span = _duration_arg(duration)
    fade_out_at = _duration_arg(max(0.0, duration - music.fade_out))
    parts = [f"[{input_index}:a]aresample={_SAMPLE_RATE}", "aformat=channel_layouts=stereo"]
    if music.track.gain_db:
        parts.append(f"volume={_duration_arg(music.track.gain_db)}dB")
    parts += [
        f"atrim=end={span}",
        f"afade=t=in:st=0:d={_duration_arg(music.fade_in)}",
        f"afade=t=out:st={fade_out_at}:d={_duration_arg(music.fade_out)}",
        f"apad=whole_dur={span}",
        f"atrim=end={span}",
    ]
    return ",".join(parts) + f"[{label}]"


def build_mix_command(
    video: Path,
    tracks: Sequence[AudioTrack],
    duration: float,
    output: Path,
    music: MusicMix | None = None,
) -> list[str]:
    """ffmpeg 参数（含可执行文件名）。每条旁白轨 `adelay` 到自己的起点，`amix` 不归一化，
    `apad=whole_dur` + `atrim` + `-t` 把总时长钉在 `duration`；没有旁白轨也没有配乐时补一条
    静音 AAC 轨，成片总有音轨。有 `music` 时配乐是最后一个输入：只有配乐就是整条音轨；
    有旁白且 `duck_under_narration` 时，旁白总线 `asplit` 后一路做侧链压低配乐，再与旁白相加。"""
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
    if not tracks and music is None:
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
        cut = "" if track.max_seconds is None else f"atrim=end={_duration_arg(track.max_seconds)},"
        delayed.append(f"[{index + 1}:a]{cut}adelay={millis}|{millis}[a{index}]")
    labels = "".join(f"[a{index}]" for index in range(len(tracks)))
    # 补静音到至少 `duration`、再裁到 `duration`：两端都有限。裸 `apad` 是无限流，遇上
    # 引擎自己编码的视频时 ffmpeg 会一直写下去，`-t` 也拦不住（2B T8 实测）。
    span = _duration_arg(duration)
    finish = f"apad=whole_dur={span},atrim=end={span}"
    if music is None:
        graph = (
            ";".join(delayed)
            + f";{labels}amix=inputs={len(tracks)}:normalize=0:duration=longest,{finish}[aout]"
        )
        return [*head, *inputs, "-filter_complex", graph, "-map", "0:v", "-map", "[aout]", *tail]

    inputs += ["-i", str(music.track.path)]
    chain = _music_chain(music, len(tracks) + 1, duration, "mus")
    if not tracks:
        graph = chain.replace("[mus]", "[aout]")
    elif music.duck_under_narration:
        graph = (
            ";".join(delayed)
            + f";{labels}amix=inputs={len(tracks)}:normalize=0:duration=longest[bus]"
            + ";[bus]asplit=2[narration][sidechain]"
            + f";{chain}"
            + f";[mus][sidechain]sidechaincompress={_DUCK}[ducked]"
            + f";[narration][ducked]amix=inputs=2:normalize=0:duration=longest,{finish}[aout]"
        )
    else:
        graph = (
            ";".join(delayed)
            + f";{chain}"
            + f";{labels}[mus]amix=inputs={len(tracks) + 1}:normalize=0:duration=longest,"
            + f"{finish}[aout]"
        )
    return [*head, *inputs, "-filter_complex", graph, "-map", "0:v", "-map", "[aout]", *tail]


async def mix_final(
    video: Path,
    tracks: Sequence[AudioTrack],
    duration: float,
    output: Path,
    *,
    music: MusicMix | None = None,
) -> None:
    """混音并写到 `output`；先写同目录的临时文件，成功后原子改名，失败不留半成品。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(f"{output.stem}.tmp{output.suffix}")
    command = build_mix_command(video, tracks, duration, temp, music)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
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
