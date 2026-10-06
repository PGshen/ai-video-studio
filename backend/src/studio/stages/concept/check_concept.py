"""`concept/brief.md` 的结构检查与 `check_concept` 工具（子项目 3 设计 §6.1、produce 设计 §4）。

只检查章节齐全、有内容、目标时长能解析出秒数，不评价内容（「硬性要求」也只看有没有写）。
错误阻止定稿；章节顺序不对或出现
约定之外的章节只是警告。
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.stages.common.target_duration import parse_target_seconds
from studio.timeline.lyrics import LYRICS_PATH, LyricsError, parse_lrc
from studio.timeline.schema import LyricLine

SECTIONS: tuple[str, ...] = (
    "主题",
    "目标时长",
    "硬性要求",
    "情绪与能量走向",
    "视觉母题",
    "参考与灵感",
    "段落草图",
    "风险点",
)
LYRICS_SECTION = "歌词意象"
"""Required (right after 「视觉母题」) only when the project has `music/lyrics.lrc`."""
BRIEF_PATH = "concept/brief.md"
DURATION_SECTION = "目标时长"

_WHITESPACE = re.compile(r"[\s\u3000]+")
_QUOTE_EXAMPLES = 3
_MIN_QUOTE_CHARS = 2

_FENCE = re.compile(r"^\s*(```|~~~)")
_H2 = re.compile(r"^##\s+(.*?)\s*#*\s*$")
_NUMBERING = re.compile(r"^\s*(?:[0-9]+|[一二三四五六七八九十]+)\s*[.、．)）]\s*")


@dataclass(slots=True)
class ConceptCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    target_seconds: float | None = None
    found_sections: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def _split_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _H2.match(line)
        if heading:
            sections.append((_NUMBERING.sub("", heading.group(1)).strip(), []))
        elif sections:
            sections[-1][1].append(line)
    return [(name, "\n".join(lines).strip()) for name, lines in sections]


def sections_for(*, has_lyrics: bool) -> tuple[str, ...]:
    if not has_lyrics:
        return SECTIONS
    at = SECTIONS.index("视觉母题") + 1
    return (*SECTIONS[:at], LYRICS_SECTION, *SECTIONS[at:])


def _squeeze(text: str) -> str:
    return _WHITESPACE.sub("", text)


def _quotes_a_lyric(body: str, lyrics: Sequence[LyricLine]) -> bool:
    """Whether `body` repeats at least one real lyric line verbatim (whitespace ignored).

    One-character lines ("啊") match too easily, so they only count when no longer line exists."""
    squeezed = _squeeze(body)
    texts = [_squeeze(line.text) for line in lyrics]
    long = [t for t in texts if len(t) >= _MIN_QUOTE_CHARS]
    return any(t and t in squeezed for t in (long or texts))


def check_concept_text(text: str, lyrics: Sequence[LyricLine] | None = None) -> ConceptCheck:
    """`lyrics` is `None` without lyrics; given, 「歌词意象」 becomes a required section."""
    result = ConceptCheck()
    sections = sections_for(has_lyrics=bool(lyrics))
    if not text.strip():
        result.errors.append(f"{BRIEF_PATH} 为空")
        return result
    parsed = _split_sections(text)
    seen: dict[str, str] = {}
    for name, body in parsed:
        seen.setdefault(name, body)
    names = [name for name, _ in parsed]
    for name in sections:
        if name not in seen:
            result.errors.append(f"缺少章节「{name}」")
        elif not seen[name]:
            result.errors.append(f"章节「{name}」没有内容")
    result.found_sections = sum(1 for name in sections if seen.get(name))
    if seen.get(DURATION_SECTION):
        result.target_seconds = parse_target_seconds(seen[DURATION_SECTION])
        if result.target_seconds is None:
            result.errors.append("「目标时长」要写成带单位的数字，例如「30 秒」或「1 分钟」")
    if lyrics and seen.get(LYRICS_SECTION) and not _quotes_a_lyric(seen[LYRICS_SECTION], lyrics):
        examples = "；".join(f"「{line.text}」" for line in lyrics[:_QUOTE_EXAMPLES])
        result.errors.append(
            f"「{LYRICS_SECTION}」里没有逐字引用任何一句歌词（music/lyrics.lrc），"
            f"请写成「歌词原句 → 画面」的形式，例如：{examples}"
        )
    for name in dict.fromkeys(names):
        if name not in sections:
            result.warnings.append(f"出现约定之外的章节「{name}」")
    expected = [name for name in sections if name in names]
    if [name for name in dict.fromkeys(names) if name in sections] != expected:
        result.warnings.append("章节顺序和约定不一致（建议按：" + "、".join(sections) + "）")
    return result


def workspace_lyrics(workdir: Path) -> list[LyricLine]:
    """`music/lyrics.lrc` as lines (the song's length is not known here, so no end clamp);
    no file gives `[]`. A broken file raises `LyricsError`."""
    path = workdir / LYRICS_PATH
    if not path.is_file():
        return []
    try:
        return parse_lrc(path.read_bytes(), math.inf)
    except OSError as exc:
        raise LyricsError([f"无法读取：{exc}"]) from exc


def check_workspace(workdir: Path) -> ConceptCheck:
    path = workdir / BRIEF_PATH
    try:
        lyrics = workspace_lyrics(workdir)
    except LyricsError as exc:
        return ConceptCheck(errors=[f"{LYRICS_PATH}：{exc}。请在画布上重新上传歌词，或删除它。"])
    if not path.is_file():
        return ConceptCheck(errors=[f"{BRIEF_PATH} 不存在"])
    return check_concept_text(path.read_text(encoding="utf-8"), lyrics)


def format_check(result: ConceptCheck) -> str:
    lines: list[str] = []
    if result.errors:
        lines.append(f"概念简报结构检查没有通过（{len(result.errors)} 个错误）：")
        lines += [f"- {e}" for e in result.errors]
    else:
        lines.append(f"概念简报结构检查通过（目标时长 {result.target_seconds:g} 秒）。")
    if result.warnings:
        lines.append(f"警告（{len(result.warnings)} 条，不阻止定稿）：")
        lines += [f"- {w}" for w in result.warnings]
    return "\n".join(lines)


class CheckConceptArgs(BaseModel):
    pass


def _handler(ctx: ToolContext, args: CheckConceptArgs) -> ToolResult:
    result = check_workspace(ctx.workdir)
    return ToolResult(text=format_check(result), is_error=not result.ok)


CHECK_CONCEPT_TOOL = ToolSpec(
    name="check_concept",
    description=(
        "检查 concept/brief.md 的结构：八个章节（含「硬性要求」）是否齐全且有内容，"
        "「目标时长」是否带单位；工作区有歌词（music/lyrics.lrc）时多一章「歌词意象」，"
        "且其中要逐字引用歌词原句。"
        "写完或改完简报后调用，错误全部修完再交给用户定稿。"
    ),
    input_model=CheckConceptArgs,
    stages={"concept"},
    handler=_handler,
)
