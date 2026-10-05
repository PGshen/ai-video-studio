"""配乐分析（子项目 3 设计 §7.3）：对齐类与观感类指标、能量曲线、波形包络、事件校验。

对齐类指标可以当硬检查（时长、声明值、事件格式），起音与网格对齐率、事件匹配率只报告；
观感类（削波、响度、段落走向）只给警告和数字。指标不评价好不好听。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeGuard

import numpy as np

from studio.engines.audio.wav import Samples

# ---- 常量（调参集中在这里） ---------------------------------------------------------
FFT_SIZE = 2048
HOP = 512
ONSET_THRESHOLD = 0.12
MIN_FLUX = 0.5
"""归一化之前的谱流量下限：低于它说明几乎没有起音（静音或纯底噪）。"""
GRID_TOLERANCE = 0.03
MATCH_TOLERANCE = 0.04
MIN_DETECTABLE_START = 0.05
ENERGY_HOP = 0.1
ENERGY_WINDOW = 0.2
ENERGY_DB_RANGE = (-40.0, -6.0)
WAVEFORM_POINTS = 1000
DURATION_TOLERANCE = 0.05
BPM_TOLERANCE = 0.01
BPM_RANGE = (40.0, 240.0)
EVENT_KINDS = ("onset", "sweep")
CLIP_LEVEL = 0.999
QUIET_PEAK = 0.3
REEL_RMS_TARGET = (-16.0, -9.0)
BED_RMS_TARGET = (-30.0, -20.0)
ENERGY_RANK = {"low": 0, "mid": 1, "high": 2, "peak": 3}
_TREND_MARGIN_DB = 0.5
_CHUNK_FRAMES = 1500
_MAX_UNMATCHED = 20


@dataclass(frozen=True, slots=True)
class SectionStat:
    id: str
    rms_dbfs: float
    centroid_hz: float


@dataclass(frozen=True, slots=True)
class EventMatch:
    name: str
    detectable: int
    matched: int


@dataclass(slots=True)
class MusicReport:
    duration: float
    sample_rate: int
    channels: int
    peak_dbfs: float
    clipped_samples: int
    rms_dbfs: float
    sections: list[SectionStat]
    onsets: list[float]
    grid_alignment: float | None
    event_matches: list[EventMatch]
    undetectable: list[dict[str, Any]]
    unmatched: list[dict[str, Any]]
    energy_hop: float
    energy: list[float]
    waveform: list[float]
    warnings: list[str] = field(default_factory=list)


def _db(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def _rms(data: np.ndarray) -> float:
    return float(np.sqrt(np.mean(data**2))) if len(data) else 0.0


def _onsets(mono: np.ndarray, sample_rate: int) -> list[float]:
    if len(mono) < FFT_SIZE:
        mono = np.pad(mono, (0, FFT_SIZE - len(mono)))
    window = np.hanning(FFT_SIZE)
    frames = 1 + (len(mono) - FFT_SIZE) // HOP
    flux = np.zeros(frames)
    previous: np.ndarray | None = None
    for start in range(0, frames, _CHUNK_FRAMES):
        stop = min(frames, start + _CHUNK_FRAMES)
        view = np.lib.stride_tricks.sliding_window_view(
            mono[start * HOP : (stop - 1) * HOP + FFT_SIZE], FFT_SIZE
        )[::HOP]
        logs = np.log1p(20.0 * np.abs(np.fft.rfft(view * window, axis=1)))
        if previous is not None:
            logs = np.vstack([previous, logs])
            offset = start - 1
        else:
            offset = start
        rises = np.maximum(0.0, np.diff(logs, axis=0)).sum(axis=1)
        flux[offset + 1 : offset + 1 + len(rises)] = rises[: frames - offset - 1]
        previous = logs[-1:]
    top = float(flux.max())
    if top < MIN_FLUX:
        return []
    flux = flux / top
    times: list[float] = []
    for i in range(2, frames - 2):
        if flux[i] > ONSET_THRESHOLD and flux[i] == flux[i - 2 : i + 3].max():
            times.append(round((i * HOP + FFT_SIZE / 2) / sample_rate, 6))
    return times


def _grid_alignment(onsets: list[float], grid: Mapping[str, Any] | None) -> float | None:
    if not onsets or not grid or not isinstance(grid.get("bpm"), int | float):
        return None
    sixteenth = 60.0 / float(grid["bpm"]) / 4.0
    offset = float(grid.get("offset", 0.0))
    near = [
        abs(((t - offset) / sixteenth + 0.5) % 1.0 - 0.5) * sixteenth < GRID_TOLERANCE
        for t in onsets
    ]
    return float(np.mean(near))


def _match_events(
    onsets: list[float], events: Sequence[Mapping[str, Any]]
) -> tuple[list[EventMatch], list[dict[str, Any]], list[dict[str, Any]]]:
    onset_events = sorted(
        (e for e in events if e.get("kind") == "onset"), key=lambda e: float(e["start"])
    )
    stats: dict[str, list[int]] = {}
    undetectable: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    previous_starts: list[float] = []
    for event in onset_events:
        name, start = str(event["name"]), float(event["start"])
        row = stats.setdefault(name, [0, 0])
        reason = None
        if start < MIN_DETECTABLE_START:
            reason = "起点早于 50 ms（检测器没有前一帧）"
        elif any(0 <= start - other < MATCH_TOLERANCE for other in previous_starts):
            reason = "与另一事件相距不足 40 ms，无法区分"
        previous_starts.append(start)
        if reason is not None:
            undetectable.append({"name": name, "start": start, "reason": reason})
            continue
        row[0] += 1
        if any(abs(t - start) <= MATCH_TOLERANCE for t in onsets):
            row[1] += 1
        else:
            unmatched.append({"name": name, "start": start})
    matches = [EventMatch(name, d, m) for name, (d, m) in stats.items()]
    return matches, undetectable, unmatched[:_MAX_UNMATCHED]


def _energy(mono: np.ndarray, sample_rate: int, duration: float) -> list[float]:
    count = int(duration / ENERGY_HOP + 1e-9) + 1
    squares = np.concatenate([[0.0], np.cumsum(mono.astype(np.float64) ** 2)])
    half = ENERGY_WINDOW / 2
    low_db, high_db = ENERGY_DB_RANGE
    values: list[float] = []
    for k in range(count):
        lo = max(0, int(round((k * ENERGY_HOP - half) * sample_rate)))
        hi = min(len(mono), int(round((k * ENERGY_HOP + half) * sample_rate)))
        if hi <= lo:
            values.append(0.0)
            continue
        rms = math.sqrt((squares[hi] - squares[lo]) / (hi - lo))
        values.append(round(min(1.0, max(0.0, (_db(rms) - low_db) / (high_db - low_db))), 3))
    return values


def _waveform(mono: np.ndarray) -> list[float]:
    buckets = min(WAVEFORM_POINTS, len(mono))
    if buckets == 0:
        return []
    edges = np.linspace(0, len(mono), buckets + 1).astype(int)
    peaks = np.maximum.reduceat(np.abs(mono), edges[:-1])
    return [round(float(v), 4) for v in peaks]


def _section_stats(
    mono: np.ndarray, sample_rate: int, timeline: Mapping[str, Any]
) -> list[SectionStat]:
    stats: list[SectionStat] = []
    for section in timeline.get("sections", []):
        part = mono[int(section["start"] * sample_rate) : int(section["end"] * sample_rate)]
        if len(part) < 2:
            continue
        spectrum = np.abs(np.fft.rfft(part * np.hanning(len(part))))
        freqs = np.fft.rfftfreq(len(part), 1.0 / sample_rate)
        total = float(spectrum.sum())
        centroid = float((freqs * spectrum).sum() / total) if total > 0 else 0.0
        stats.append(SectionStat(section["id"], _db(_rms(part)), centroid))
    return stats


def analyze(
    samples: Samples,
    timeline: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    *,
    section_energy: Mapping[str, str] | None = None,
) -> MusicReport:
    mono = samples.mono()
    sr = samples.sample_rate
    peak = float(np.max(np.abs(samples.data))) if len(samples.data) else 0.0
    clipped = int(np.sum(np.abs(samples.data) >= CLIP_LEVEL))
    overall = _db(_rms(mono))
    onsets = _onsets(mono, sr)
    matches, undetectable, unmatched = _match_events(onsets, events)
    sections = _section_stats(mono, sr, timeline)
    duration = float(timeline.get("duration") or samples.duration)
    report = MusicReport(
        duration=samples.duration,
        sample_rate=sr,
        channels=samples.channels,
        peak_dbfs=_db(peak),
        clipped_samples=clipped,
        rms_dbfs=overall,
        sections=sections,
        onsets=onsets,
        grid_alignment=_grid_alignment(onsets, timeline.get("grid")),
        event_matches=matches,
        undetectable=undetectable,
        unmatched=unmatched,
        energy_hop=ENERGY_HOP,
        energy=_energy(mono, sr, duration),
        waveform=_waveform(mono),
    )
    report.warnings = _warnings(report, timeline, section_energy or {})
    return report


def _warnings(
    report: MusicReport, timeline: Mapping[str, Any], section_energy: Mapping[str, str]
) -> list[str]:
    warnings: list[str] = []
    if report.clipped_samples:
        warnings.append(f"削波：{report.clipped_samples} 个样本达到满幅，请降低总增益或加限幅")
    if report.peak_dbfs < _db(QUIET_PEAK):
        warnings.append(
            f"整体过轻（峰值 {report.peak_dbfs:.1f} dBFS）；静音或几乎无声时检查合成逻辑"
        )
    bed = bool(timeline.get("narration"))
    low, high = BED_RMS_TARGET if bed else REEL_RMS_TARGET
    if report.peak_dbfs >= _db(QUIET_PEAK) and not low <= report.rms_dbfs <= high:
        kind = "背景乐" if bed else "短片"
        warnings.append(
            f"整体 RMS {report.rms_dbfs:.1f} dBFS 不在{kind}目标范围 {low:g}–{high:g} dBFS 内"
        )
    for before, after in zip(report.sections, report.sections[1:], strict=False):
        rank_before = ENERGY_RANK.get(section_energy.get(before.id, ""), None)
        rank_after = ENERGY_RANK.get(section_energy.get(after.id, ""), None)
        if rank_before is None or rank_after is None or rank_after <= rank_before:
            continue
        if after.rms_dbfs < before.rms_dbfs + _TREND_MARGIN_DB:
            warnings.append(
                f"{before.id}（{section_energy[before.id]}）到 {after.id}"
                f"（{section_energy[after.id]}）节拍脚本要求能量上升，"
                f"实测 RMS 从 {before.rms_dbfs:.1f} 到 {after.rms_dbfs:.1f} dBFS"
            )
    return warnings


def _number(value: Any) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def validate_events(doc: Any, timeline: Mapping[str, Any]) -> list[str]:
    """`events.json` 的结构与声明值检查；有旁白的项目不核对 bpm（网格取自它），但必须声明。"""
    if not isinstance(doc, dict):
        return ["events.json 的顶层应为对象 {bpm, duration, events}"]
    problems: list[str] = []
    duration = float(timeline.get("duration") or 0.0)
    bpm = doc.get("bpm")
    low, high = BPM_RANGE
    if not _number(bpm) or not low <= bpm <= high:
        problems.append(f"bpm 必须是 {low:g}–{high:g} 之间的数字（当前 {bpm!r}）")
    else:
        grid = timeline.get("grid")
        if not timeline.get("narration") and grid and abs(bpm - float(grid["bpm"])) > BPM_TOLERANCE:
            problems.append(f"声明的 bpm {bpm} 与节拍脚本的 {grid['bpm']} 不一致")
    declared = doc.get("duration")
    if not _number(declared) or abs(declared - duration) > DURATION_TOLERANCE:
        problems.append(f"声明的 duration {declared!r} 与时间轴 {duration:.3f} 相差超过 0.05 秒")
    events = doc.get("events")
    if not isinstance(events, list):
        problems.append("events 必须是列表")
        return problems
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            problems.append(f"事件 {index}：应为对象")
            continue
        name, kind = event.get("name"), event.get("kind")
        start, end = event.get("start"), event.get("end")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"事件 {index}：名称必须是非空字符串")
        elif kind not in EVENT_KINDS:
            problems.append(f"事件 {index}（{name}）：kind 必须是 onset 或 sweep（当前 {kind!r}）")
        elif not _number(start) or not _number(end) or end < start:
            problems.append(
                f"事件 {index}（{name}）：起止必须是数字且 start ≤ end（{start!r}→{end!r}）"
            )
        elif start < -DURATION_TOLERANCE or end > duration + DURATION_TOLERANCE:
            problems.append(
                f"事件 {index}（{name}）：起止 {start}→{end} 超出时间轴 [0, {duration:.3f}]"
            )
    return problems
