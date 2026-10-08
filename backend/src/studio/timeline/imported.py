"""歌曲（MV）分析结果的网格换算（produce 设计 §6）。

纯函数，只处理已解析的 dict。`analysis.json` 里的 BPM 与第一个强拍是**参考值**：模型可以不采用，
所以这里不再有"段落""节拍脚本""强拍对齐"。`import_hash` 给 MV 时间轴哈希加上源文件与截取区间。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from studio.timeline.build import BPM_RANGE, TimelineError
from studio.timeline.numeric import BEATS_PER_BAR, EPSILON, is_finite_number

_MAX_DOWNBEATS = 100_000


def effective_grid(analysis: dict[str, Any]) -> tuple[float, float]:
    """分析给出的 `(bpm, offset)`（`offset` 是第一个强拍的秒数）；不合法时抛 `TimelineError`。"""
    if not isinstance(analysis, dict):
        raise TimelineError(["music/analysis.json 的顶层不是对象"])
    errors: list[str] = []
    values: dict[str, float] = {}
    for key in ("bpm", "offset"):
        value = analysis.get(key)
        if not is_finite_number(value):
            errors.append(f"music/analysis.json：{key} 必须是有限的数字（当前 {value!r}）")
            continue
        values[key] = float(value)
    bpm = values.get("bpm")
    low, high = BPM_RANGE
    if bpm is not None and not low <= bpm <= high:
        errors.append(f"BPM 必须在 {low:g}–{high:g} 之间（当前 {bpm!r}）")
    if errors:
        raise TimelineError(errors)
    return values["bpm"], values["offset"]


def downbeat_times(bpm: float, offset: float, duration: float) -> list[float]:
    """`[0, duration]` 内的全部强拍时刻（全局秒）：`offset + k·小节`，`k` 可为负。"""
    if not is_finite_number(bpm) or bpm <= 0:
        raise TimelineError([f"BPM 必须是正的有限数字（当前 {bpm!r}）"])
    if not is_finite_number(offset):
        raise TimelineError([f"offset 必须是有限的数字（当前 {offset!r}）"])
    if not is_finite_number(duration) or duration < 0:
        raise TimelineError([f"duration 必须是非负的有限数字（当前 {duration!r}）"])
    bar = BEATS_PER_BAR * 60.0 / bpm
    if duration / bar > _MAX_DOWNBEATS:
        raise TimelineError([f"强拍数量过多（BPM {bpm}，时长 {duration}）"])
    k = math.ceil(-offset / bar - EPSILON)
    times: list[float] = []
    while (t := offset + k * bar) <= duration + EPSILON:
        times.append(round(t, 6))
        k += 1
    return times


def import_hash(timeline_digest: str, source_hash: str, range_: tuple[float, float]) -> str:
    """MV 的时间轴哈希：`sha256(timeline_hash + source_hash + range)`（schema 不改字段）。"""
    payload = f"{timeline_digest}{source_hash}{range_[0]:.6f}-{range_[1]:.6f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["downbeat_times", "effective_grid", "import_hash"]
