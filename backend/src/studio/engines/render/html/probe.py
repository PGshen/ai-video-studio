"""校验与预览用的探针（设计 §6.3）：采样、冒烟运行、确定性、beat 敏感度、缩略图拼图。

只依赖 `PageLike` 协议（取帧、替换时间轴、收集页面错误），不关心页面来自真实 Chromium 还是替身。
"""

from __future__ import annotations

import copy
import io
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageStat

from studio.engines.render.html.browser import BrowserClosed, PageLike, RenderTimeout

FLAT_STD = 3.0
SHIFT_SECONDS = 0.7
_SENSITIVITY_OFFSETS = (0.1, 0.4, 0.7, 1.0, 1.4)
_MIN_GAP_PX = (480, 270)


@dataclass(frozen=True, slots=True)
class FrameMetrics:
    mean: float
    std: float


@dataclass(slots=True)
class SceneSmoke:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: list[tuple[float, FrameMetrics]] = field(default_factory=list)
    frames: list[tuple[float, bytes]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SensitivityReport:
    tested: list[int]
    insensitive_beats: list[int]
    skipped: list[int]
    all_insensitive: bool


def section_info(
    timeline: Mapping[str, Any], scene_id: str
) -> tuple[float, float, list[dict[str, Any]]]:
    section = next((s for s in timeline["sections"] if s["id"] == scene_id), None)
    if section is None:
        raise KeyError(scene_id)
    entry = next((n for n in timeline["narration"] if n["scene_id"] == scene_id), None)
    beats = list(entry["beats"]) if entry else []
    return float(section["start"]), float(section["end"]), beats


def sample_times(
    start: float,
    end: float,
    beats: list[dict[str, Any]],
    *,
    uniform: int = 12,
    cap: int = 16,
) -> list[float]:
    """必选点（镜头首尾、每个 beat 的起点与终点附近）优先；有余量时再补均匀采样点。"""

    def inside(values: set[float]) -> list[float]:
        return sorted({round(t, 6) for t in values if start <= t < end})

    required = {start + 0.05, end - 0.05}
    for beat in beats:
        required.add(beat["start"] + 0.3)
        required.add(beat["end"] - 0.1)
    times = inside(required)
    while len(times) > cap:
        gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
        i = gaps.index(min(gaps))
        times.pop(i + 1 if i + 1 < len(times) - 1 else i)
    extras = inside({start + (end - start) * (i + 0.5) / uniform for i in range(uniform)})
    if not times and extras:
        times.append(extras.pop(0))
    while len(times) < cap and extras:
        best = max(extras, key=lambda c: min(abs(c - t) for t in times))
        extras.remove(best)
        times.append(best)
        times.sort()
    return times


def frame_metrics(jpeg: bytes) -> FrameMetrics:
    stat = ImageStat.Stat(Image.open(io.BytesIO(jpeg)).convert("L"))
    return FrameMetrics(mean=float(stat.mean[0]), std=float(stat.stddev[0]))


def is_flat(metrics: FrameMetrics) -> bool:
    return metrics.std < FLAT_STD


def contact_sheet(
    frames: list[tuple[str, bytes]], cols: int = 4, thumb: tuple[int, int] = (480, 270)
) -> bytes:
    if not frames:
        raise ValueError("没有可拼接的帧")
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb[0], rows * thumb[1]), (30, 30, 30))
    for index, (label, jpeg) in enumerate(frames):
        cell = Image.open(io.BytesIO(jpeg)).convert("RGB").resize(thumb)
        draw = ImageDraw.Draw(cell)
        draw.rectangle([0, 0, 8 + 6 * len(label), 14], fill=(0, 0, 0))
        draw.text((3, 1), label, fill=(255, 255, 0))
        sheet.paste(cell, ((index % cols) * thumb[0], (index // cols) * thumb[1]))
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    return buffer.getvalue()


def _gray(jpeg: bytes) -> Image.Image:
    return Image.open(io.BytesIO(jpeg)).convert("L").resize(_MIN_GAP_PX)


async def boundary_diff(page: PageLike, boundary_t: float) -> float:
    """边界前后各 0.02 秒两帧的平均绝对灰度差（0–255）。"""
    before = _gray(await page.render_jpeg(max(boundary_t - 0.02, 0.0)))
    after = _gray(await page.render_jpeg(boundary_t + 0.02))
    return float(ImageStat.Stat(ImageChops.difference(before, after)).mean[0])


def _error_key(message: str) -> str:
    first = message.splitlines()[0] if message else ""
    return re.sub(r"@lt=[\d.]+", "", first)


async def smoke_run(page: PageLike, timeline: Mapping[str, Any], scene_id: str) -> SceneSmoke:
    start, end, beats = section_info(timeline, scene_id)
    report = SceneSmoke()
    seen: set[str] = set()
    flat_times: list[float] = []
    known_errors = len(page.errors)  # 只归因于本次运行期间新出现的页面错误
    for t in sample_times(start, end, beats):
        try:
            jpeg = await page.render_jpeg(t)
        except RenderTimeout:
            report.errors.append(f"镜头 {scene_id} 在 lt={t - start:.2f} 渲染超时（可能有死循环）")
            break
        except BrowserClosed:
            raise
        except Exception as exc:  # 镜头里的异常已带 [scene <id> @lt=…] 前缀
            key = _error_key(str(exc))
            if key not in seen:
                seen.add(key)
                report.errors.append(str(exc))
            continue
        metrics = frame_metrics(jpeg)
        report.metrics.append((t, metrics))
        report.frames.append((t, jpeg))
        if is_flat(metrics):
            flat_times.append(t)
    if flat_times:
        report.warnings.append(
            f"{len(flat_times)} 个采样帧画面空白或纯色（首个在 t={flat_times[0]:.2f}s）"
        )
    for message in dict.fromkeys(page.errors[known_errors:]):
        if message.startswith("console.warning"):
            report.warnings.append(message)
        elif _error_key(message) not in seen:
            seen.add(_error_key(message))
            report.errors.append(message)
    return report


async def determinism_check(page: PageLike, times: list[float]) -> list[float]:
    """正序、倒序各渲染一遍，返回两次结果不一致的时刻（镜头依赖了调用顺序或外部状态）。"""
    forward = {t: await page.render_hash(t) for t in times}
    backward = {t: await page.render_hash(t) for t in reversed(times)}
    return [t for t in times if forward[t] != backward[t]]


async def beat_sensitivity(
    page: PageLike,
    timeline: Mapping[str, Any],
    scene_id: str,
    *,
    shift: float = SHIFT_SECONDS,
) -> SensitivityReport:
    """逐个 beat 后移 `shift` 秒，在相同局部时间重渲染；画面没变说明该 beat 没驱动画面。"""
    start, end, beats = section_info(timeline, scene_id)
    length = end - start
    tested: list[int] = []
    insensitive: list[int] = []
    skipped: list[int] = []
    await page.set_timeline(timeline)
    try:
        for i, beat in enumerate(beats):
            cue = beat["start"] - start
            if cue + shift > length - 0.2:
                skipped.append(i)
                continue
            probes = [start + cue + d for d in _SENSITIVITY_OFFSETS if cue + d < length - 0.05]
            await page.set_timeline(timeline)
            original = [await page.render_hash(t) for t in probes]
            modified = copy.deepcopy(dict(timeline))
            entry = next(n for n in modified["narration"] if n["scene_id"] == scene_id)
            for later in entry["beats"][i:]:
                later["start"] += shift
                later["end"] += shift
            await page.set_timeline(modified)
            changed = [await page.render_hash(t) for t in probes]
            tested.append(i)
            if changed == original:
                insensitive.append(i)
    finally:
        if not page.poisoned:
            await page.set_timeline(timeline)
    return SensitivityReport(
        tested=tested,
        insensitive_beats=insensitive,
        skipped=skipped,
        all_insensitive=bool(tested) and len(insensitive) == len(tested),
    )
