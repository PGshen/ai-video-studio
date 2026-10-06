"""`validate_sections` 工具与校验逻辑（4A 设计 §4、计划 T5）。

纯函数 `check_sections(doc, analysis)` 检查 `music/sections.json`：段落 id、顺序、首尾相接并恰好覆盖
有效截取区间、起止对齐强拍（容差 `ALIGN_TOLERANCE`）且吸附到不同的强拍（每段至少一小节）、
落在音频长度内。畸形输入（非字典、缺字段、类型错误、布尔当数字、非有限数）一律转成错误条目，不抛异常。
"""

from __future__ import annotations

import json
import math
import re
from bisect import bisect_left
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeGuard

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.stages.common.score.sources import import_source
from studio.timeline import TimelineError
from studio.timeline.build import BPM_RANGE
from studio.timeline.imported import ALIGN_TOLERANCE, downbeat_times, effective_grid

SECTIONS_PATH = "music/sections.json"
ANALYSIS_PATH = "music/analysis.json"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_JOIN_TOLERANCE = 1e-3
"""秒；相邻段落首尾相接、`range` 与段落跨度一致的判定容差（只吸收取整误差）。"""
_EPS = 1e-9
NOT_IMPORT_MESSAGE = (
    "还没有上传音乐：validate_sections 只用于导入形态（music/source.*）；"
    "合成形态请写 music/compose.py 并用 render_music"
)


@dataclass(slots=True)
class SectionsCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    section_count: int = 0
    range: tuple[float, float] | None = None
    """有效截取区间（秒）；无法确定时为 `None`。"""

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_number(value: Any) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _grid(doc: dict[str, Any], analysis: dict[str, Any], duration: float, check: SectionsCheck):
    """有效网格 `(bpm, offset)`；覆盖值与分析值都做范围检查，不合法返回 `None`。"""
    low, high = BPM_RANGE
    start = len(check.errors)
    bpm_override = doc.get("bpm")
    if bpm_override is not None and (
        not _is_number(bpm_override) or not low <= bpm_override <= high
    ):
        check.errors.append(
            f"sections.json 的 bpm 必须是 {low:g}–{high:g} 之间的数字（当前 {bpm_override!r}）"
        )
    offset_override = doc.get("offset")
    if offset_override is not None and (
        not _is_number(offset_override) or not 0 <= offset_override < duration
    ):
        check.errors.append(
            f"sections.json 的 offset 必须是 0 到音频时长 {duration:g} 之间的数字"
            f"（当前 {offset_override!r}）"
        )
    if len(check.errors) > start:
        return None
    try:
        bpm, offset = effective_grid(analysis, doc)
    except TimelineError as exc:
        check.errors.extend(exc.errors)
        return None
    if not 0 <= offset < duration:
        check.errors.append(
            f"offset 必须是 0 到音频时长 {duration:g} 之间的数字（当前 {offset!r}，"
            "来自 analysis.json）"
        )
        return None
    return bpm, offset


def _nearest(downbeats: list[float], value: float) -> float | None:
    if not downbeats:
        return None
    index = bisect_left(downbeats, value)
    candidates = downbeats[max(0, index - 1) : index + 1]
    return min(candidates, key=lambda t: abs(t - value))


def _check_aligned(
    what: str, value: float, downbeats: list[float], check: SectionsCheck
) -> float | None:
    """`value` 吸附到的强拍；没对齐时记一条错误并返回 `None`。"""
    nearest = _nearest(downbeats, value)
    if nearest is None:
        check.errors.append(f"{what} {value:g} s 没有落在强拍上（音频内没有强拍）")
        return None
    if abs(nearest - value) > ALIGN_TOLERANCE + _EPS:
        check.errors.append(
            f"{what} {value:g} s 没有落在强拍上（最近的强拍 {nearest:g} s，"
            f"相差 {abs(nearest - value) * 1000:.0f} ms，容差 {ALIGN_TOLERANCE * 1000:.0f} ms）"
        )
        return None
    return nearest


@dataclass(frozen=True, slots=True)
class _Section:
    id: str
    start: float
    end: float


def _parse_sections(doc: dict[str, Any], check: SectionsCheck) -> list[_Section]:
    raw = doc.get("sections")
    if not isinstance(raw, list) or not raw:
        check.errors.append("sections 必须是非空列表")
        return []
    parsed: list[_Section] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            check.errors.append(f"第 {index} 个段落不是对象")
            continue
        section_id = item.get("id")
        if not isinstance(section_id, str) or not _ID_PATTERN.match(section_id):
            check.errors.append(
                f"第 {index} 个段落的 id 必须是只含字母、数字、下划线、连字符的字符串"
                f"（当前 {section_id!r}）"
            )
            continue
        if section_id in seen:
            check.errors.append(f"段落 id {section_id} 重复")
            continue
        seen.add(section_id)
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            check.warnings.append(f"段落 {section_id} 的 label 为空，请写有意义的标签（如 verse）")
        start, end = item.get("start"), item.get("end")
        if not _is_number(start) or not _is_number(end):
            check.errors.append(
                f"段落 {section_id} 的 start/end 必须是有限的数字（{start!r}→{end!r}）"
            )
            continue
        if not start < end:
            check.errors.append(
                f"段落 {section_id} 的起点必须小于终点（start {start:g} ≥ end {end:g}）"
            )
            continue
        parsed.append(_Section(section_id, float(start), float(end)))
    return parsed


def _check_order(sections: list[_Section], check: SectionsCheck) -> None:
    for prev, current in zip(sections, sections[1:], strict=False):
        if current.start < prev.start - _JOIN_TOLERANCE:
            check.errors.append(f"段落顺序错误：{current.id} 排在 {prev.id} 之后但起点更早")
        elif current.start < prev.end - _JOIN_TOLERANCE:
            check.errors.append(
                f"段落 {prev.id} 与 {current.id} 重叠（{prev.id} 到 {prev.end:g} s，"
                f"{current.id} 从 {current.start:g} s 开始）"
            )
        elif current.start > prev.end + _JOIN_TOLERANCE:
            check.errors.append(
                f"段落 {prev.id} 与 {current.id} 之间有空隙（{prev.end:g}–{current.start:g} s）；"
                "段落必须首尾相接，想裁掉的部分不要写成段落"
            )


def _check_range(
    doc: dict[str, Any], sections: list[_Section], check: SectionsCheck
) -> tuple[float, float]:
    span = (sections[0].start, sections[-1].end)
    raw = doc.get("range")
    if raw is None:
        return span
    if not isinstance(raw, dict):
        check.errors.append(f"range 必须是 {{start, end}} 对象（当前 {raw!r}）")
        return span
    start, end = raw.get("start"), raw.get("end")
    if not _is_number(start) or not _is_number(end) or not start < end:
        check.errors.append(f"range 的起止必须是有限的数字且 start < end（{start!r}→{end!r}）")
        return span
    if abs(start - span[0]) > _JOIN_TOLERANCE or abs(end - span[1]) > _JOIN_TOLERANCE:
        check.errors.append(
            f"range {start:g}→{end:g} 必须与段落跨度 {span[0]:g}→{span[1]:g} 一致"
            "（要裁掉前奏或尾声，就不要写那几段，或同时调整 range）"
        )
    return float(start), float(end)


def check_sections(doc: Any, analysis: Any) -> SectionsCheck:
    check = SectionsCheck()
    if not isinstance(analysis, dict):
        check.errors.append("analysis.json 的顶层不是对象，请重新 analyze_music")
        return check
    if not isinstance(doc, dict):
        check.errors.append("sections.json 的顶层必须是对象")
        return check
    duration = analysis.get("duration")
    if not _is_number(duration) or duration <= 0:
        check.errors.append(f"analysis.json 的 duration 无效（{duration!r}），请重新 analyze_music")
        return check
    grid = _grid(doc, analysis, float(duration), check)
    sections = _parse_sections(doc, check)
    check.section_count = len(sections)
    if not sections:
        return check
    _check_order(sections, check)
    effective = _check_range(doc, sections, check)
    check.range = effective
    for section in sections:
        if section.start < -ALIGN_TOLERANCE or section.end > duration + ALIGN_TOLERANCE:
            check.errors.append(
                f"段落 {section.id} 的 {section.start:g}→{section.end:g} s "
                f"超出音频范围 [0, {duration:g}] s"
            )
    if effective[0] < -ALIGN_TOLERANCE or effective[1] > duration + ALIGN_TOLERANCE:
        check.errors.append(
            f"range {effective[0]:g}→{effective[1]:g} s 超出音频范围 [0, {duration:g}] s"
        )
    if grid is None:
        return check
    try:
        downbeats = downbeat_times(grid[0], grid[1], float(duration))
    except TimelineError as exc:
        check.errors.extend(exc.errors)
        return check
    for section in sections:
        start = _check_aligned(f"段落 {section.id} 的起点", section.start, downbeats, check)
        end = _check_aligned(f"段落 {section.id} 的终点", section.end, downbeats, check)
        if start is not None and start == end:
            check.errors.append(
                f"段落 {section.id} 不足一小节：{section.start:g}→{section.end:g} s 的起点和终点"
                f"吸附到同一个强拍 {start:g} s，每个段落至少要跨一小节（起止落在不同的强拍上）"
            )
    if doc.get("range") is not None and isinstance(doc["range"], dict):
        start, end = doc["range"].get("start"), doc["range"].get("end")
        if _is_number(start) and _is_number(end):
            _check_aligned("range 的起点", float(start), downbeats, check)
            _check_aligned("range 的终点", float(end), downbeats, check)
    return check


def check_workspace(workdir: Path) -> SectionsCheck:
    analysis_path = workdir / ANALYSIS_PATH
    if not analysis_path.is_file():
        return SectionsCheck(errors=[f"{ANALYSIS_PATH} 不存在，请先 analyze_music"])
    sections_path = workdir / SECTIONS_PATH
    if not sections_path.is_file():
        return SectionsCheck(errors=[f"{SECTIONS_PATH} 不存在，请先写出它"])
    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return SectionsCheck(
            errors=[f"{ANALYSIS_PATH} 不是合法的 JSON：{exc}，请重新 analyze_music"]
        )
    try:
        doc = json.loads(sections_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return SectionsCheck(errors=[f"{SECTIONS_PATH} 不是合法的 JSON：{exc}"])
    return check_sections(doc, analysis)


def format_check(result: SectionsCheck) -> str:
    lines: list[str] = []
    if result.errors:
        lines.append(f"段落校验没有通过（{len(result.errors)} 个错误）：")
        lines += [f"- {e}" for e in result.errors]
    else:
        assert result.range is not None
        lines.append(
            f"段落校验通过：{result.section_count} 个段落，"
            f"截取区间 {result.range[0]:g}–{result.range[1]:g} 秒。"
        )
    if result.warnings:
        lines.append(f"警告（{len(result.warnings)} 条，不阻止定稿）：")
        lines += [f"- {w}" for w in result.warnings]
    return "\n".join(lines)


class ValidateSectionsArgs(BaseModel):
    pass


def _handler(ctx: ToolContext, args: ValidateSectionsArgs) -> ToolResult:
    if import_source(ctx.workdir) is None:
        return ToolResult(text=NOT_IMPORT_MESSAGE, is_error=True)
    result = check_workspace(ctx.workdir)
    return ToolResult(text=format_check(result), is_error=not result.ok)


VALIDATE_SECTIONS_TOOL = ToolSpec(
    name="validate_sections",
    description=(
        "校验 music/sections.json：段落 id 合法唯一、有序、首尾相接并覆盖截取区间、"
        "起止对齐强拍（容差 30 ms）、落在音频长度内；range 必须与段落跨度一致且对齐强拍。"
        "需要先 analyze_music，只用于导入形态。写完或改完 sections.json 后调用，错误会一次列全。"
    ),
    input_model=ValidateSectionsArgs,
    stages={"music"},
    handler=_handler,
)
