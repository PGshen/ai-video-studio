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
from studio.timeline.notation import parse_at

BEATSHEET_PATH = "beatsheet/beatsheet.json"
BRIEF_PATH = "upstream/concept/brief.md"
BPM_RANGE = (60.0, 200.0)
MAX_SECTIONS = 12
TOTAL_RANGE = (8.0, 180.0)
WARN_DEVIATION = 0.15
ERROR_DEVIATION = 0.40
ENERGY_VALUES = ("low", "mid", "high", "peak")
BEATS_PER_BAR = 4

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_EPSILON = 1e-6


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
    section_id: str, moments: Any, bpm: float, bars: int, check: BeatsheetCheck
) -> None:
    if moments is None:
        return
    if not isinstance(moments, list):
        check.errors.append(f"段落 {section_id}：moments 必须是列表")
        return
    section_seconds = bars * BEATS_PER_BAR * 60.0 / bpm
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
                f"{label}：at {moment['at']} 没有落在本段内（本段只有 {bars} 小节）"
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
            _check_moments(shown, section.get("moments"), bpm_value, bars, check)

    if bpm_value is not None and bars_ok:
        total = total_bars * BEATS_PER_BAR * 60.0 / bpm_value
        check.total_seconds = total
        low_s, high_s = TOTAL_RANGE
        if not low_s <= total <= high_s:
            check.errors.append(
                f"总时长 {total:.2f} 秒不在 {low_s:g}–{high_s:g} 秒之内（总小节数 × 4 × 60 / BPM）"
            )
        if target_seconds is None:
            check.warnings.append("没有读到 upstream/concept/brief.md 的目标时长，无法核对总时长")
        else:
            deviation = abs(total - target_seconds) / target_seconds
            detail = f"总时长 {total:.2f} 秒与目标时长 {target_seconds:g} 秒相差 {deviation:.0%}"
            if deviation > ERROR_DEVIATION:
                check.errors.append(detail + f"，超过 {ERROR_DEVIATION:.0%}")
            elif deviation > WARN_DEVIATION:
                check.warnings.append(detail + f"，超过 {WARN_DEVIATION:.0%}")
    return check


def _target_from_workspace(workdir: Path) -> float | None:
    path = workdir / BRIEF_PATH
    if not path.is_file():
        return None
    return target_seconds_from_brief(path.read_text(encoding="utf-8"))


def check_workspace(workdir: Path) -> BeatsheetCheck:
    path = workdir / BEATSHEET_PATH
    if not path.is_file():
        return BeatsheetCheck(errors=[f"{BEATSHEET_PATH} 不存在"])
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return BeatsheetCheck(errors=[f"{BEATSHEET_PATH} 不是合法的 JSON：{exc}"])
    return check_beatsheet(doc, target_seconds=_target_from_workspace(workdir))


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
        "总时长与概念简报里的目标时长是否吻合。写完或改完后调用，错误全部修完再交给用户定稿。"
    ),
    input_model=ValidateBeatsheetArgs,
    stages={"beatsheet"},
    handler=_handler,
)
