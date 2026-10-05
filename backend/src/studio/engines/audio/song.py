"""导入歌曲的分析（子项目 4 设计 §4）：解码、拟合恒定网格。

纯能力层：只依赖标准库、NumPy、librosa 和系统 ffmpeg，不 import `studio.timeline`
（BPM 范围在此定义同值常量，测试断言两处一致）。
"""

from __future__ import annotations

import math
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from studio.engines.audio.wav import AudioError, Samples

# ---- 常量（调参集中在这里） ---------------------------------------------------------
ANALYSIS_SAMPLE_RATE = 22050
MAX_SONG_SECONDS = 600
MIN_SONG_SECONDS = 5.0
SILENCE_PEAK = 10 ** (-60.0 / 20.0)
"""峰值低于约 -60 dBFS 视为静音。"""
BPM_MIN = 40.0
BPM_MAX = 240.0
"""与 `studio.timeline.build.BPM_RANGE` 同值；超出就无法生成时间轴。"""
FOLD_MIN = 60.0
FOLD_MAX = 200.0
"""倍频/半频折算的优先区间（流行音乐的常见速度），落在 BPM_MIN–BPM_MAX 之内。"""
MIN_BEATS = 4
OUTLIER_FLOOR_S = 0.025
OUTLIER_SIGMAS = 3.0
_OUTLIER_ROUNDS = 4
_DECODE_TIMEOUT = 120.0


@dataclass(frozen=True, slots=True)
class GridFit:
    bpm: float
    offset: float
    """第 0 拍的时刻（秒）。"""
    residual_ms: float
    """剔除离群拍点后，拟合残差的 RMS（毫秒）。"""
    beats_used: int


def decode_song(path: Path, *, ffmpeg: str = "ffmpeg") -> Samples:
    """用 ffmpeg 统一转成 22050 Hz 单声道 float 再读；失败、静音、过短、过长都抛 `AudioError`。"""
    if not path.is_file():
        raise AudioError(f"{path.name} 不存在")
    command = [
        ffmpeg, "-v", "error", "-nostdin", "-i", str(path), "-vn",
        "-t", str(MAX_SONG_SECONDS + 1),
        "-ac", "1", "-ar", str(ANALYSIS_SAMPLE_RATE), "-f", "f32le", "-",
    ]  # fmt: skip
    try:
        done = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=_DECODE_TIMEOUT,
            check=False,
        )
    except FileNotFoundError:
        raise AudioError(f"找不到 ffmpeg（{ffmpeg}），无法解码 {path.name}") from None
    except subprocess.TimeoutExpired:
        raise AudioError(f"解码 {path.name} 超时（{_DECODE_TIMEOUT:.0f} 秒）") from None
    if done.returncode != 0 or not done.stdout:
        tail = done.stderr.decode("utf-8", errors="replace").strip().splitlines()[-3:]
        raise AudioError(f"{path.name} 无法解码，可能不是有效的音频文件：{' '.join(tail)}")
    usable = len(done.stdout) - len(done.stdout) % 4
    data = np.frombuffer(done.stdout[:usable], dtype="<f4").astype(np.float64)
    if not np.isfinite(data).all():
        raise AudioError(f"{path.name} 解码后含 NaN 或无穷大的样本")
    samples = Samples(data=data, sample_rate=ANALYSIS_SAMPLE_RATE)
    if samples.duration > MAX_SONG_SECONDS:
        raise AudioError(f"歌曲过长：超过上限 {MAX_SONG_SECONDS} 秒")
    if samples.duration < MIN_SONG_SECONDS:
        raise AudioError(f"歌曲过短：{samples.duration:.1f} 秒，至少需要 {MIN_SONG_SECONDS:g} 秒")
    if float(np.max(np.abs(data))) < SILENCE_PEAK:
        raise AudioError(f"{path.name} 是静音（峰值低于 -60 dBFS），无法分析节拍")
    return samples


def _fold(bpm: float) -> float:
    """按倍频/半频折算进 [FOLD_MIN, FOLD_MAX]；折算不进 [BPM_MIN, BPM_MAX] 就放弃。"""
    if not math.isfinite(bpm) or bpm <= 0:
        raise AudioError(f"无法从拍点得到有效的 BPM（{bpm}）")
    folded = bpm
    while folded > FOLD_MAX and folded / 2 >= BPM_MIN:
        folded /= 2
    while folded < FOLD_MIN and folded * 2 <= BPM_MAX:
        folded *= 2
    if not BPM_MIN <= folded <= BPM_MAX:
        raise AudioError(
            f"拟合出的 BPM {bpm:.1f} 无法折算进 {BPM_MIN:g}–{BPM_MAX:g}；这首歌的拍点不可靠"
        )
    return folded


def _indices(times: np.ndarray, period: float) -> np.ndarray:
    """拍点序号：用相邻间隔累加，而不是直接除以起点，避免周期误差累积成整拍错位。"""
    steps = np.maximum(1, np.rint(np.diff(times) / period)).astype(int)
    return np.concatenate([[0], np.cumsum(steps)])


def fit_grid(beat_times: Sequence[float]) -> GridFit:
    """对拍点序号做线性最小二乘，得到 `bpm`、`offset`；先迭代剔除残差过大的离群拍点。"""
    times = np.sort(np.asarray([float(t) for t in beat_times], dtype=np.float64))
    if len(times) < MIN_BEATS or not np.isfinite(times).all():
        raise AudioError(f"检测到的拍点太少（{len(times)} 个，至少 {MIN_BEATS} 个），无法拟合节拍")
    period = float(np.median(np.diff(times)))
    if period <= 0:
        raise AudioError("拍点时间没有递增，无法拟合节拍")
    index = _indices(times, period)
    keep = np.ones(len(times), dtype=bool)
    slope, intercept = period, float(times[0])
    for _ in range(_OUTLIER_ROUNDS):
        if keep.sum() < MIN_BEATS:
            break
        slope, intercept = np.polyfit(index[keep], times[keep], 1)
        residual = times - (intercept + slope * index)
        spread = 1.4826 * float(np.median(np.abs(residual[keep] - np.median(residual[keep]))))
        limit = max(OUTLIER_SIGMAS * spread, OUTLIER_FLOOR_S)
        updated = np.abs(residual) <= limit
        if updated.sum() < MIN_BEATS or (updated == keep).all():
            break
        keep = updated
        index = _indices(times[keep], float(slope)).astype(int)
        full = np.full(len(times), -1, dtype=int)
        full[keep] = index
        # Dropped beats still need an index for the next residual check.
        full[~keep] = np.rint((times[~keep] - intercept) / slope).astype(int)
        index = full
    slope, intercept = np.polyfit(index[keep], times[keep], 1)
    residual = times[keep] - (intercept + slope * index[keep])
    bpm = _fold(60.0 / float(slope))
    return GridFit(
        bpm=bpm,
        offset=float(intercept),
        residual_ms=float(np.sqrt(np.mean(residual**2)) * 1000.0),
        beats_used=int(keep.sum()),
    )
