"""MV 来源（导入音乐，4A 设计 §5）：分析、段落与节拍脚本三份文档 → 时间轴各层。

纯函数，只处理已解析的 dict；读文件在 `load.py`。所有问题汇总成 `TimelineError`，畸形输入
（类型不对、非有限数）也不会抛出别的异常——`validate_sections` 与 MV 节拍脚本校验复用这里的
`effective_grid`、`downbeat_times`。

时间约定：`sections.json` 与 `analysis.json` 里是相对源文件的全局秒；时间轴以有效截取区间的起点
为 0。有效区间是显式 `range`，缺省取第一段起点到最后一段终点。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, TypeGuard

from studio.timeline.build import (
    BPM_RANGE,
    GridInput,
    MomentInput,
    MusicInput,
    TimedSectionInput,
    TimelineError,
    TimelineLayers,
    build_timeline,
)

ALIGN_TOLERANCE = 0.03
"""秒；起止“落在强拍上”的容差。区间起点离强拍不超过它即视为从强拍开始（网格 offset 为 0）。"""
_BEATS_PER_BAR = 4
_EPSILON = 1e-6
_MAX_DOWNBEATS = 100_000


@dataclass(frozen=True, slots=True)
class ImportLayers:
    layers: TimelineLayers
    source_hash: str
    range: tuple[float, float]
    """有效截取区间（全局秒）。"""
    source_file: str | None
    """`music/source.<ext>`；为 `None` 时不含 `music` 层。"""


def _is_number(value: Any) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _grid_values(analysis: Any, sections_doc: Any, errors: list[str]) -> tuple[float, float] | None:
    if not isinstance(analysis, dict):
        errors.append("music/analysis.json 的顶层不是对象")
    if not isinstance(sections_doc, dict):
        errors.append("music/sections.json 的顶层不是对象")
    if not isinstance(analysis, dict) or not isinstance(sections_doc, dict):
        return None
    values: dict[str, float] = {}
    for key in ("bpm", "offset"):
        override = sections_doc.get(key)
        source, value = (
            ("music/sections.json", override)
            if override is not None
            else ("music/analysis.json", analysis.get(key))
        )
        if not _is_number(value):
            errors.append(f"{source}：{key} 必须是有限的数字（当前 {value!r}）")
            continue
        values[key] = float(value)
    bpm = values.get("bpm")
    low, high = BPM_RANGE
    if bpm is not None and not low <= bpm <= high:
        errors.append(f"BPM 必须在 {low:g}–{high:g} 之间（当前 {bpm!r}）")
        return None
    if len(values) != 2:
        return None
    return values["bpm"], values["offset"]


def effective_grid(analysis: dict[str, Any], sections_doc: dict[str, Any]) -> tuple[float, float]:
    """有效的 `(bpm, offset)`：`sections.json` 给出的优先，否则取分析值。

    `offset` 是第一个强拍的时刻（全局秒）。不合法时抛 `TimelineError`。
    """
    errors: list[str] = []
    grid = _grid_values(analysis, sections_doc, errors)
    if errors or grid is None:
        raise TimelineError(errors or ["无法确定节拍网格"])
    return grid


def effective_range(sections_doc: dict[str, Any]) -> tuple[float, float]:
    """有效截取区间（全局秒）：`range` 给出的优先，否则取段落的整体跨度。

    预览、成片与 `music/meta` 共用这一条规则；文档不合法时抛 `TimelineError`。
    """
    errors: list[str] = []
    sections = _raw_sections(sections_doc, errors)
    explicit = _explicit_range(sections_doc, errors)
    if errors or not sections:
        raise TimelineError(errors or ["music/sections.json 没有段落"])
    if explicit is not None:
        return explicit
    return sections[0].start, sections[-1].end


def downbeat_times(bpm: float, offset: float, duration: float) -> list[float]:
    """`[0, duration]` 内的全部强拍时刻（全局秒）：`offset + k·小节`，`k` 可为负。"""
    if not _is_number(bpm) or bpm <= 0:
        raise TimelineError([f"BPM 必须是正的有限数字（当前 {bpm!r}）"])
    if not _is_number(offset):
        raise TimelineError([f"offset 必须是有限的数字（当前 {offset!r}）"])
    if not _is_number(duration) or duration < 0:
        raise TimelineError([f"duration 必须是非负的有限数字（当前 {duration!r}）"])
    bar = _BEATS_PER_BAR * 60.0 / bpm
    if duration / bar > _MAX_DOWNBEATS:
        raise TimelineError([f"强拍数量过多（BPM {bpm}，时长 {duration}）"])
    k = math.ceil(-offset / bar - _EPSILON)
    times: list[float] = []
    while (t := offset + k * bar) <= duration + _EPSILON:
        times.append(round(t, 6))
        k += 1
    return times


def _positive(doc: dict[str, Any], key: str, errors: list[str]) -> float | None:
    value = doc.get(key)
    if not _is_number(value) or value <= 0:
        errors.append(f"music/analysis.json：{key} 必须是正的有限数字（当前 {value!r}）")
        return None
    return float(value)


@dataclass(frozen=True, slots=True)
class _RawSection:
    id: str
    label: str
    start: float
    end: float


def _raw_sections(sections_doc: dict[str, Any], errors: list[str]) -> list[_RawSection]:
    raw = sections_doc.get("sections")
    if not isinstance(raw, list) or not raw:
        errors.append("music/sections.json：sections 必须是非空列表")
        return []
    result: list[_RawSection] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            errors.append(f"music/sections.json：第 {index} 个段落缺少字符串 id")
            continue
        section_id = item["id"]
        start, end = item.get("start"), item.get("end")
        if not _is_number(start) or not _is_number(end):
            errors.append(
                f"music/sections.json：段落 {section_id} 的起止必须是有限的数字"
                f"（{start!r}→{end!r}）"
            )
            continue
        label = item.get("label")
        result.append(
            _RawSection(
                section_id,
                label if isinstance(label, str) and label.strip() else section_id,
                float(start),
                float(end),
            )
        )
    return result


def _explicit_range(sections_doc: dict[str, Any], errors: list[str]) -> tuple[float, float] | None:
    raw = sections_doc.get("range")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        errors.append(f"music/sections.json：range 必须是 {{start, end}} 对象（当前 {raw!r}）")
        return None
    start, end = raw.get("start"), raw.get("end")
    if not _is_number(start) or not _is_number(end) or not start < end:
        errors.append(
            f"music/sections.json：range 的起止必须是有限的数字且 start < end（{start!r}→{end!r}）"
        )
        return None
    return float(start), float(end)


def _energy(analysis: dict[str, Any], errors: list[str]) -> list[float] | None:
    energy = analysis.get("energy")
    if not isinstance(energy, list) or not all(_is_number(v) for v in energy):
        errors.append("music/analysis.json：energy 必须是数字列表")
        return None
    return [float(v) for v in energy]


def _grid_offset(bpm: float, offset: float, start: float) -> float:
    """区间起点之后（含容差内的起点本身）第一个强拍相对起点的秒数。"""
    bar = _BEATS_PER_BAR * 60.0 / bpm
    k = math.ceil((start - offset - ALIGN_TOLERANCE) / bar)
    return round(max(0.0, offset + k * bar - start), 6)


def _moments(beatsheet: Any, section_ids: set[str], errors: list[str]) -> list[MomentInput]:
    if not isinstance(beatsheet, dict) or not isinstance(beatsheet.get("sections"), list):
        errors.append("beatsheet.json：sections 必须是列表")
        return []
    moments: list[MomentInput] = []
    for index, raw in enumerate(beatsheet["sections"]):
        if not isinstance(raw, dict) or not isinstance(raw.get("ref"), str):
            name = raw.get("id") if isinstance(raw, dict) else None
            errors.append(
                f"beatsheet.json：第 {index} 个段落（{name!r}）缺少字符串 ref"
                "（MV 的段落用 ref 指向 music/sections.json 的段落 id）"
            )
            continue
        ref = raw["ref"]
        if ref not in section_ids:
            errors.append(
                f"beatsheet.json：ref {ref!r} 在 music/sections.json 的有效区间内没有对应段落"
            )
            continue
        raw_moments = raw.get("moments") or []
        if not isinstance(raw_moments, list):
            errors.append(f"beatsheet.json：段落 {ref} 的 moments 必须是列表")
            continue
        for moment in raw_moments:
            if not isinstance(moment, dict) or not isinstance(moment.get("at"), str):
                errors.append(f"beatsheet.json：段落 {ref} 有节拍脚本点缺少字符串 at")
                continue
            action = moment.get("visual_action")
            moments.append(
                MomentInput(ref, moment["at"], action if isinstance(action, str) else "")
            )
    return moments


def layers_from_import(
    analysis: dict[str, Any],
    sections_doc: dict[str, Any],
    beatsheet: dict[str, Any] | None,
    *,
    source_file: str | None = None,
) -> ImportLayers:
    """三份文档 → 时间轴各层（以有效区间起点为 0）。

    `beatsheet` 为 `None` 时没有节拍脚本点；`source_file` 为 `None` 时不含 `music` 层。
    这里只做结构与区间检查，段落相接、点位越界等在 `build_timeline`。
    """
    errors: list[str] = []
    grid = _grid_values(analysis, sections_doc, errors)
    if not isinstance(analysis, dict) or not isinstance(sections_doc, dict):
        raise TimelineError(errors)

    raw_hash = analysis.get("source_hash")
    source_hash = raw_hash if isinstance(raw_hash, str) else ""
    if not source_hash:
        errors.append(f"music/analysis.json：source_hash 必须是非空字符串（当前 {raw_hash!r}）")
    duration = _positive(analysis, "duration", errors)
    hop = _positive(analysis, "hop", errors)
    energy = _energy(analysis, errors)
    raw_sections = _raw_sections(sections_doc, errors)
    explicit = _explicit_range(sections_doc, errors)
    if errors or grid is None or duration is None or hop is None or energy is None:
        raise TimelineError(errors or ["无法确定节拍网格"])

    start, end = explicit if explicit is not None else (raw_sections[0].start, raw_sections[-1].end)
    if start < -ALIGN_TOLERANCE or end > duration + ALIGN_TOLERANCE:
        what = "range" if explicit is not None else "段落跨度"
        errors.append(
            f"music/sections.json：{what} {start}→{end} 超出音频范围 [0, duration={duration}]"
        )

    timed: list[TimedSectionInput] = []
    for section in raw_sections:
        if section.end <= start + _EPSILON or section.start >= end - _EPSILON:
            continue  # entirely outside the range
        timed.append(
            TimedSectionInput(
                section.id,
                section.label,
                round(max(section.start, start) - start, 6),
                round(min(section.end, end) - start, 6),
            )
        )
    length = round(end - start, 6)
    if not timed:
        errors.append(f"music/sections.json：range {start}→{end} 内没有任何段落")
    else:
        if timed[0].start > _EPSILON:
            errors.append(f"music/sections.json：range 起点 {start} 没有段落覆盖")
        if timed[-1].end < length - _EPSILON:
            errors.append(f"music/sections.json：range 终点 {end} 没有段落覆盖")

    if errors:
        raise TimelineError(errors)
    moments = (
        _moments(beatsheet, {section.id for section in timed}, errors)
        if beatsheet is not None
        else []
    )

    bpm, offset = grid
    music = None
    if source_file is not None:
        first = max(0, int(round(start / hop)))
        count = max(1, int(round((end - start) / hop)))
        music = MusicInput(
            events=[],
            energy_hop=hop,
            energy_values=energy[first : first + count],
            file=source_file,
        )
    layers = TimelineLayers(
        [],
        grid=GridInput(bpm, _grid_offset(bpm, offset, start)),
        moments=moments,
        music=music,
        timed_sections=timed,
    )
    if errors:
        # Report beatsheet problems together with what the build would find in the other layers.
        try:
            build_timeline(layers)
        except TimelineError as exc:
            errors.extend(exc.errors)
        raise TimelineError(errors)
    return ImportLayers(layers, source_hash, (round(start, 6), round(end, 6)), source_file)


def import_hash(timeline_digest: str, source_hash: str, range_: tuple[float, float]) -> str:
    """MV 的时间轴哈希：`sha256(timeline_hash + source_hash + range)`（schema 不改字段）。"""
    payload = f"{timeline_digest}{source_hash}{range_[0]:.6f}-{range_[1]:.6f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "effective_range",
    "ALIGN_TOLERANCE",
    "ImportLayers",
    "downbeat_times",
    "effective_grid",
    "import_hash",
    "layers_from_import",
]
