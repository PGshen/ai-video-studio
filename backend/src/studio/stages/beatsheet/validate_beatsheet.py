"""`validate_beatsheet` 工具与校验逻辑（子项目 3 设计 §6.2）。

纯函数 `check_beatsheet(doc, target_seconds)` 逐项检查 `beatsheet/beatsheet.json`；错误一次列全，
阻止定稿；警告（空 intent、缺目标时长、与目标时长偏差 15%–40% 等）不阻止。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeGuard

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.stages.common.target_duration import target_seconds_from_brief
from studio.timeline import TimelineError
from studio.timeline.imported import effective_grid
from studio.timeline.notation import parse_at

BEATSHEET_PATH = "beatsheet/beatsheet.json"
BRIEF_PATH = "upstream/concept/brief.md"
MV_SECTIONS_PATH = "upstream/music/sections.json"
MV_ANALYSIS_PATH = "upstream/music/analysis.json"
BPM_RANGE = (60.0, 200.0)
MAX_SECTIONS = 12
TOTAL_RANGE = (8.0, 180.0)
WARN_DEVIATION = 0.15
ERROR_DEVIATION = 0.40
ENERGY_VALUES = ("low", "mid", "high", "peak")
BEATS_PER_BAR = 4

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_EPSILON = 1e-6
_RANGE_TOLERANCE = 1e-3


@dataclass(slots=True)
class BeatsheetCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_seconds: float | None = None
    bpm: float | None = None
    section_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_number(value: Any) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _check_moments(
    section_id: str,
    moments: Any,
    bpm: float,
    section_seconds: float,
    length_text: str,
    check: BeatsheetCheck,
) -> None:
    if moments is None:
        return
    if not isinstance(moments, list):
        check.errors.append(f"段落 {section_id}：moments 必须是列表")
        return
    previous = -1.0
    for index, moment in enumerate(moments):
        label = f"段落 {section_id} 的第 {index + 1} 个 moment"
        if not isinstance(moment, dict) or not isinstance(moment.get("at"), str):
            check.errors.append(f'{label}：缺少字符串 at（小节.拍，例如 "2.3"）')
            continue
        try:
            offset = parse_at(moment["at"], bpm, BEATS_PER_BAR)
        except ValueError as exc:
            check.errors.append(f"{label}：at {moment['at']!r} 不是合法的小节.拍写法（{exc}）")
            continue
        if offset >= section_seconds - _EPSILON:
            check.errors.append(
                f"{label}：at {moment['at']} 没有落在本段内（本段只有 {length_text}）"
            )
            continue
        if offset < previous - _EPSILON:
            check.errors.append(f"{label}：at {moment['at']} 比前一个 moment 早，请按时间顺序写")
        previous = max(previous, offset)
        action = moment.get("visual_action")
        if not isinstance(action, str) or not action.strip():
            check.warnings.append(f"{label}：visual_action 为空，画面阶段不知道要做什么")


def check_beatsheet(doc: Any, *, target_seconds: float | None) -> BeatsheetCheck:
    check = BeatsheetCheck()
    if not isinstance(doc, dict):
        check.errors.append("beatsheet.json 的顶层应为对象 {bpm, sections}")
        return check
    bpm = doc.get("bpm")
    low, high = BPM_RANGE
    bpm_value: float | None = None
    if _is_number(bpm) and low <= bpm <= high:
        bpm_value = float(bpm)
        check.bpm = bpm_value
    else:
        check.errors.append(f"BPM 必须是 {low:g}–{high:g} 之间的数字（当前 {bpm!r}）")
    sections = doc.get("sections")
    if not isinstance(sections, list) or not sections:
        check.errors.append("sections 必须是非空的段落列表")
        return check
    if len(sections) > MAX_SECTIONS:
        check.errors.append(f"段落太多（{len(sections)} 个，最多 {MAX_SECTIONS} 个）")
    check.section_count = len(sections)

    seen: set[str] = set()
    total_bars = 0
    bars_ok = True
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            check.errors.append(f"第 {index + 1} 个段落应为对象")
            bars_ok = False
            continue
        section_id = section.get("id")
        shown = section_id if isinstance(section_id, str) and section_id else f"#{index + 1}"
        if not isinstance(section_id, str) or not _ID_PATTERN.match(section_id):
            check.errors.append(
                f"第 {index + 1} 个段落的 id {section_id!r} 不合法："
                "只能是字母、数字、下划线、连字符"
            )
        elif section_id in seen:
            check.errors.append(f"段落 id {section_id} 重复")
        else:
            seen.add(section_id)
        bars = section.get("bars")
        if not isinstance(bars, int) or isinstance(bars, bool) or bars < 1:
            check.errors.append(f"段落 {shown}：bars 必须是正整数（当前 {bars!r}）")
            bars_ok = False
        else:
            total_bars += bars
        if section.get("energy") not in ENERGY_VALUES:
            allowed = "/".join(ENERGY_VALUES)
            check.errors.append(
                f"段落 {shown}：energy 必须是 {allowed} 之一（当前 {section.get('energy')!r}）"
            )
        if not isinstance(section.get("intent"), str) or not section["intent"].strip():
            check.warnings.append(f"段落 {shown}：intent 为空，写一句这段要表达什么")
        if not isinstance(section.get("label"), str) or not section["label"].strip():
            check.warnings.append(f"段落 {shown}：没有 label，将用 id 代替")
        if (
            bpm_value is not None
            and isinstance(bars, int)
            and not isinstance(bars, bool)
            and bars >= 1
        ):
            _check_moments(
                shown,
                section.get("moments"),
                bpm_value,
                bars * BEATS_PER_BAR * 60.0 / bpm_value,
                f"{bars} 小节",
                check,
            )

    if bpm_value is not None and bars_ok:
        total = total_bars * BEATS_PER_BAR * 60.0 / bpm_value
        check.total_seconds = total
        low_s, high_s = TOTAL_RANGE
        if not low_s <= total <= high_s:
            check.errors.append(
                f"总时长 {total:.2f} 秒不在 {low_s:g}–{high_s:g} 秒之内（总小节数 × 4 × 60 / BPM）"
            )
        _check_target(total, target_seconds, check)
    return check


def _check_target(total: float, target_seconds: float | None, check: BeatsheetCheck) -> None:
    if target_seconds is None:
        check.warnings.append("没有读到 upstream/concept/brief.md 的目标时长，无法核对总时长")
        return
    deviation = abs(total - target_seconds) / target_seconds
    detail = f"总时长 {total:.2f} 秒与目标时长 {target_seconds:g} 秒相差 {deviation:.0%}"
    if deviation > ERROR_DEVIATION:
        check.errors.append(detail + f"，超过 {ERROR_DEVIATION:.0%}")
    elif deviation > WARN_DEVIATION:
        check.warnings.append(detail + f"，超过 {WARN_DEVIATION:.0%}")


def _finite(value: Any) -> TypeGuard[float]:
    return _is_number(value) and value == value and abs(value) != float("inf")


def _upstream_sections(sections_doc: Any, check: BeatsheetCheck) -> list[tuple[str, float, float]]:
    """`(id, start, end)` of every upstream section; problems become errors."""
    raw = sections_doc.get("sections") if isinstance(sections_doc, dict) else None
    if not isinstance(raw, list) or not raw:
        check.errors.append("music/sections.json：sections 必须是非空列表")
        return []
    result: list[tuple[str, float, float]] = []
    for index, item in enumerate(raw):
        section_id: Any = None
        start: Any = None
        end: Any = None
        if isinstance(item, dict):
            section_id, start, end = item.get("id"), item.get("start"), item.get("end")
        if not (isinstance(section_id, str) and _finite(start) and _finite(end) and end > start):
            check.errors.append(
                f"music/sections.json：第 {index + 1} 个段落缺少字符串 id 或合法的起止时间"
            )
            return []
        result.append((section_id, float(start), float(end)))
    return result


def _check_range_matches_span(
    sections_doc: dict[str, Any], span: tuple[float, float], check: BeatsheetCheck
) -> None:
    """An explicit `range` must equal the section span (music stage rule); no clipping here."""
    explicit = sections_doc.get("range")
    if not isinstance(explicit, dict):
        return
    start, end = explicit.get("start"), explicit.get("end")
    if not (_finite(start) and _finite(end)):
        return
    if abs(start - span[0]) > _RANGE_TOLERANCE or abs(end - span[1]) > _RANGE_TOLERANCE:
        check.errors.append(
            f"music/sections.json 的 range（{start:g}→{end:g}）与段落跨度"
            f"（{span[0]:g}→{span[1]:g}）不一致，请回到 music 阶段修正"
        )


def check_beatsheet_mv(
    doc: Any, sections_doc: Any, analysis_doc: Any, *, target_seconds: float | None
) -> BeatsheetCheck:
    """MV form: sections reference `music/sections.json`; the grid comes from the music."""
    check = BeatsheetCheck()
    try:
        bpm, _offset = effective_grid(analysis_doc, sections_doc)
    except TimelineError as exc:
        check.errors.extend(exc.errors)
        return check
    upstream = _upstream_sections(sections_doc, check)
    if not upstream:
        return check
    check.bpm = bpm
    if not isinstance(doc, dict):
        check.errors.append("beatsheet.json 的顶层应为对象 {sections}")
        return check
    if "bpm" in doc:
        check.errors.append("MV 的节拍脚本不能写 bpm（节拍网格取自音乐）")
    sections = doc.get("sections")
    if not isinstance(sections, list) or not sections:
        check.errors.append("sections 必须是非空的段落列表")
        return check
    check.section_count = len(sections)

    by_id = {section_id: (start, end) for section_id, start, end in upstream}
    order = [section_id for section_id, _, _ in upstream]
    seen: set[str] = set()
    last_index = -1
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            check.errors.append(f"第 {index + 1} 个段落应为对象")
            continue
        ref = section.get("ref")
        if not isinstance(ref, str) or not ref:
            check.errors.append(
                f"第 {index + 1} 个段落缺少字符串 ref（music/sections.json 的段落 id）"
            )
            continue
        if ref not in by_id:
            check.errors.append(f"段落 {ref}：ref 在 music/sections.json 里不存在")
            continue
        if ref in seen:
            check.errors.append(f"段落 {ref}：ref 重复（每个段落只能引用一次）")
            continue
        seen.add(ref)
        position = order.index(ref)
        if position < last_index:
            check.errors.append(
                f"段落 {ref}：顺序与 music/sections.json 不一致（应在 {order[last_index]} 之前）"
            )
        last_index = max(last_index, position)
        if "id" in section and section["id"] != ref:
            check.errors.append(f"段落 {ref}：id {section['id']!r} 必须与 ref {ref!r} 一致")
        if "bars" in section:
            check.errors.append(f"段落 {ref}：MV 的段落不能写 bars（段长以音乐为准）")
        if section.get("energy") not in ENERGY_VALUES:
            allowed = "/".join(ENERGY_VALUES)
            check.errors.append(
                f"段落 {ref}：energy 必须是 {allowed} 之一（当前 {section.get('energy')!r}）"
            )
        if not isinstance(section.get("intent"), str) or not section["intent"].strip():
            check.warnings.append(f"段落 {ref}：intent 为空，写一句这段要表达什么")
        start, end = by_id[ref]
        length = end - start
        _check_moments(
            ref,
            section.get("moments"),
            bpm,
            length,
            f"{length * bpm / (BEATS_PER_BAR * 60.0):.2f} 小节",
            check,
        )
    missing = [section_id for section_id in order if section_id not in seen]
    if missing:
        check.errors.append(f"还缺少 music/sections.json 的段落：{'、'.join(missing)}")

    span = (upstream[0][1], upstream[-1][2])
    _check_range_matches_span(sections_doc, span, check)
    total = span[1] - span[0]
    check.total_seconds = total
    _check_target(total, target_seconds, check)
    return check


def _target_from_workspace(workdir: Path) -> float | None:
    path = workdir / BRIEF_PATH
    if not path.is_file():
        return None
    return target_seconds_from_brief(path.read_text(encoding="utf-8"))


def _read_json(workdir: Path, relative: str, missing_hint: str = "") -> tuple[Any, str | None]:
    path = workdir / relative
    if not path.is_file():
        return None, f"{relative} 不存在{missing_hint}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except ValueError as exc:  # includes UnicodeDecodeError
        return None, f"{relative} 不是合法的 JSON：{exc}"


def check_workspace(workdir: Path) -> BeatsheetCheck:
    """Dispatch by form: an upstream `music/sections.json` means a music video."""
    doc, error = _read_json(workdir, BEATSHEET_PATH)
    if error is not None:
        return BeatsheetCheck(errors=[error])
    target = _target_from_workspace(workdir)
    if not (workdir / MV_SECTIONS_PATH).is_file():
        return check_beatsheet(doc, target_seconds=target)
    sections_doc, error = _read_json(workdir, MV_SECTIONS_PATH)
    if error is not None:
        return BeatsheetCheck(errors=[error])
    analysis_doc, error = _read_json(workdir, MV_ANALYSIS_PATH, "（音乐阶段还没有定稿分析）")
    if error is not None:
        return BeatsheetCheck(errors=[error])
    return check_beatsheet_mv(doc, sections_doc, analysis_doc, target_seconds=target)


def format_check(result: BeatsheetCheck) -> str:
    lines: list[str] = []
    if result.errors:
        lines.append(f"节拍脚本校验没有通过（{len(result.errors)} 个错误）：")
        lines += [f"- {e}" for e in result.errors]
    else:
        lines.append(
            f"节拍脚本校验通过：{result.section_count} 个段落，BPM {result.bpm:g}，"
            f"总时长 {result.total_seconds:.2f} 秒。"
        )
    if result.warnings:
        lines.append(f"警告（{len(result.warnings)} 条，不阻止定稿）：")
        lines += [f"- {w}" for w in result.warnings]
    return "\n".join(lines)


class ValidateBeatsheetArgs(BaseModel):
    pass


def _handler(ctx: ToolContext, args: ValidateBeatsheetArgs) -> ToolResult:
    result = check_workspace(ctx.workdir)
    return ToolResult(text=format_check(result), is_error=not result.ok)


VALIDATE_BEATSHEET_TOOL = ToolSpec(
    name="validate_beatsheet",
    description=(
        "校验 beatsheet/beatsheet.json：BPM 与小节数、段落 id 与能量、moment 的小节.拍写法与范围、"
        "总时长与概念简报里的目标时长是否吻合。音乐 MV（有 upstream/music/sections.json）："
        "段落写 ref（指向 sections.json 的段落 id，顺序一致、全部引用），不写 bpm 与 bars，"
        "at 相对本段、按音乐的 BPM 换算。写完或改完后调用，错误全部修完再交给用户定稿。"
    ),
    input_model=ValidateBeatsheetArgs,
    stages={"beatsheet"},
    handler=_handler,
)
