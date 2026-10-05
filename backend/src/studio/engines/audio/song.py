"""导入歌曲的分析（子项目 4 设计 §4）：解码、拟合恒定网格、强拍相位、候选段落、能量、置信度。

纯能力层：只依赖标准库、NumPy、librosa 和系统 ffmpeg，不 import `studio.timeline`
（BPM 范围在此定义同值常量，测试断言两处一致）。
"""

from __future__ import annotations

import hashlib
import math
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from studio.engines.audio.analysis import ENERGY_HOP, energy_curve
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
_DOUBLE_GAP = 0.75
"""相邻拍点间隔小于 0.75 个周期视为多余的重复检测（半拍误检的 rint 恰为 0.5）。"""
_PHASE_FRAMES_BEFORE = 3
_PHASE_FRAMES_AFTER = 1
"""起音在拍点前后各几帧内取最大值：2048 点的窗口会让起音提前约两帧出现。"""
_DECODE_TIMEOUT = 120.0
HOP_LENGTH = 512
BEATS_PER_BAR = 4
LOW_BAND_HZ = 200.0
"""强拍相位只看这个频段以下的起音（底鼓）。"""
SECTION_SECONDS = 20.0
MIN_SECTIONS = 2
MAX_SECTIONS = 12
CONFIDENCE_RESIDUAL_FRACTION = 0.15
CONFIDENCE_WARN = 0.5
UNSTABLE_WARNING = "拍点不稳（可能是散拍或变速），请手动修正 sections.json 的 bpm/offset"
_ROUND = 6


@dataclass(frozen=True, slots=True)
class GridFit:
    bpm: float
    offset: float
    """某一拍的时刻（秒），模一拍有效：它不一定是第 0 拍，更不一定是强拍。"""
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
            f"拟合出的 BPM {bpm:.1f} 无法折算进 {BPM_MIN:g}–{BPM_MAX:g}"
            "（只有拍点极不规则时才会出现），拍点不可靠"
        )
    return folded


def _initial_keep(times: np.ndarray, period: float) -> tuple[np.ndarray, np.ndarray]:
    """First-pass indices and keep mask; beats closer than ~0.75 period to the previous
    kept beat are spurious doubles and are left out (their rint() would be 0 or 1 by luck)."""
    index = np.zeros(len(times), dtype=int)
    keep = np.zeros(len(times), dtype=bool)
    keep[0] = True
    last = 0
    for i in range(1, len(times)):
        gap = (times[i] - times[last]) / period
        if gap < _DOUBLE_GAP:
            continue
        index[i] = index[last] + max(1, int(np.rint(gap)))
        keep[i] = True
        last = i
    return index, keep


def fit_grid(beat_times: Sequence[float]) -> GridFit:
    """对拍点序号做线性最小二乘，得到 `bpm`、`offset`；先迭代剔除残差过大的离群拍点。

    每一轮都用当前拟合重新给全部拍点编号，被剔除的拍点之后仍有机会回来。
    """
    times = np.sort(np.asarray([float(t) for t in beat_times], dtype=np.float64))
    if len(times) < MIN_BEATS or not np.isfinite(times).all():
        raise AudioError(f"检测到的拍点太少（{len(times)} 个，至少 {MIN_BEATS} 个），无法拟合节拍")
    period = float(np.median(np.diff(times)))
    if period <= 0:
        raise AudioError("拍点时间没有递增，无法拟合节拍")
    index, keep = _initial_keep(times, period)
    if keep.sum() < MIN_BEATS:
        raise AudioError(
            f"检测到的拍点太少（{int(keep.sum())} 个，至少 {MIN_BEATS} 个），无法拟合节拍"
        )
    for _ in range(_OUTLIER_ROUNDS):
        slope, intercept = np.polyfit(index[keep], times[keep], 1)
        index = np.rint((times - intercept) / slope).astype(int)
        residual = times - (intercept + slope * index)
        spread = 1.4826 * float(np.median(np.abs(residual[keep] - np.median(residual[keep]))))
        limit = max(OUTLIER_SIGMAS * spread, OUTLIER_FLOOR_S)
        updated = np.abs(residual) <= limit
        # At most one beat per grid slot: keep the one closest to the line.
        for slot in np.unique(index[updated]):
            members = np.flatnonzero(updated & (index == slot))
            if len(members) > 1:
                best = members[np.argmin(np.abs(residual[members]))]
                updated[members] = False
                updated[best] = True
        if updated.sum() < MIN_BEATS or (updated == keep).all():
            break
        keep = updated
    slope, intercept = np.polyfit(index[keep], times[keep], 1)
    residual = times[keep] - (intercept + slope * index[keep])
    bpm = _fold(60.0 / float(slope))
    return GridFit(
        bpm=bpm,
        offset=float(intercept),
        residual_ms=float(np.sqrt(np.mean(residual**2)) * 1000.0),
        beats_used=int(keep.sum()),
    )


@dataclass(slots=True)
class SongAnalysis:
    """`analysis.json` 的内容；`beats`/`downbeats` 为覆盖全曲的全局秒（4/4）。"""

    source_hash: str
    duration: float
    bpm: float
    offset: float
    """第一个强拍的时刻，落在 [0, 一小节)。"""
    residual_ms: float
    confidence: float
    beats: list[float]
    downbeats: list[float]
    candidates: list[float]
    hop: float
    energy: list[float]
    warnings: list[str] = field(default_factory=list)

    def to_document(self) -> dict[str, Any]:
        def r(value: float) -> float:
            return round(float(value), _ROUND)

        return {
            "source_hash": self.source_hash,
            "duration": r(self.duration),
            "bpm": r(self.bpm),
            "offset": r(self.offset),
            "residual_ms": r(self.residual_ms),
            "confidence": r(self.confidence),
            "beats": [r(t) for t in self.beats],
            "downbeats": [r(t) for t in self.downbeats],
            "candidates": [r(t) for t in self.candidates],
            "hop": r(self.hop),
            "energy": [r(v) for v in self.energy],
            "warnings": list(self.warnings),
        }


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _low_onset_strength(y: np.ndarray, sr: int) -> np.ndarray:
    import librosa

    spectrum = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP_LENGTH))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    low = np.log1p(20.0 * spectrum[freqs < LOW_BAND_HZ])
    return np.concatenate([[0.0], np.maximum(0.0, np.diff(low, axis=1)).sum(axis=0)])


def _downbeat_phase(y: np.ndarray, sr: int, beats: np.ndarray) -> int:
    """四种相位里，各拍位置的低频起音强度之和最大者（平局取最早的相位）。"""
    flux = _low_onset_strength(y, sr)
    frames = np.rint(beats * sr / HOP_LENGTH).astype(int)
    strength = np.zeros(len(beats))
    for i, frame in enumerate(frames):
        lo = max(0, frame - _PHASE_FRAMES_BEFORE)
        hi = min(len(flux), frame + _PHASE_FRAMES_AFTER + 1)
        if hi > lo:
            strength[i] = flux[lo:hi].max()
    totals = [float(strength[p::BEATS_PER_BAR].sum()) for p in range(BEATS_PER_BAR)]
    return int(np.argmax(totals))


def _candidate_boundaries(
    y: np.ndarray, sr: int, duration: float, downbeats: np.ndarray
) -> list[float]:
    import librosa

    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=HOP_LENGTH, n_mfcc=20)
    chroma = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=HOP_LENGTH)
    features = np.vstack(
        [librosa.util.normalize(mfcc, axis=1), librosa.util.normalize(chroma, axis=1)]
    )
    count = min(MAX_SECTIONS, max(MIN_SECTIONS, round(duration / SECTION_SECONDS)))
    count = min(count, features.shape[1])
    frames = librosa.segment.agglomerative(features, count)
    times = librosa.frames_to_time(frames, sr=sr, hop_length=HOP_LENGTH)
    snapped = {float(downbeats[int(np.argmin(np.abs(downbeats - t)))]) for t in times if t > 0.0}
    return sorted(t for t in snapped if 0.0 < t < duration)


def analyze_song(path: Path, *, ffmpeg: str = "ffmpeg") -> SongAnalysis:
    """解码并分析一首歌；同一输入的结果逐位一致（无随机成分）。"""
    import librosa

    samples = decode_song(path, ffmpeg=ffmpeg)
    y, sr, duration = samples.data, samples.sample_rate, samples.duration
    _, detected = librosa.beat.beat_track(y=y, sr=sr, hop_length=HOP_LENGTH, units="time")
    fit = fit_grid([float(t) for t in detected])
    period = 60.0 / fit.bpm
    first = fit.offset % period
    beats = first + period * np.arange(int(math.floor((duration - first) / period)) + 1)
    beats = beats[beats < duration]
    phase = _downbeat_phase(y, sr, beats)
    downbeats = beats[phase::BEATS_PER_BAR]
    expected = max(1.0, duration / period)
    coverage = min(1.0, fit.beats_used / expected)
    fitness = max(0.0, 1.0 - fit.residual_ms / (CONFIDENCE_RESIDUAL_FRACTION * period * 1000.0))
    confidence = fitness * coverage
    warnings = [UNSTABLE_WARNING] if confidence < CONFIDENCE_WARN else []
    return SongAnalysis(
        source_hash=_file_hash(path),
        duration=duration,
        bpm=fit.bpm,
        offset=float(downbeats[0]),
        residual_ms=fit.residual_ms,
        confidence=confidence,
        beats=[float(t) for t in beats],
        downbeats=[float(t) for t in downbeats],
        candidates=_candidate_boundaries(y, sr, duration, downbeats),
        hop=ENERGY_HOP,
        energy=energy_curve(y, sr, duration),
        warnings=warnings,
    )
