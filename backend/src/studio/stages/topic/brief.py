"""选题简报 `topic/brief.md` 的结构与检查（设计 §5.1；计划 M4 T6）。

固定七个二级标题章节；「关键事实」章节的每个列表项遵循
`- 事实陈述（出处：<URL 或文献>；把握程度：高|中|低）`，解析容忍全半角冒号、逗号、
分号、括号，以及事实和标注分成多行。`check` 是纯函数，`check_brief` 工具和
`GET /projects/{id}/topic/check` 共用。

错误（阻止定稿的建议条件）：文件缺失/为空、缺章节、章节为空、关键事实没有列表项、
某条事实缺出处或把握程度不在 高/中/低。警告（不阻止）：低把握事实、章节顺序不对、
出现约定之外的章节、章节重复、风险点过短。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from studio.workspace import files

SECTIONS: tuple[str, ...] = (
    "核心问题",
    "钩子与反直觉点",
    "目标观众与前置知识",
    "关键事实",
    "叙事角度与结构草图",
    "可视化机会",
    "风险点",
)
FACTS_SECTION = "关键事实"
RISK_SECTION = "风险点"
MIN_RISK_CHARS = 20
CONFIDENCE_VALUES = ("高", "中", "低")
BRIEF_PATH = "topic/brief.md"

_FENCE = re.compile(r"^\s*(```|~~~)")
_H2 = re.compile(r"^##\s+(.*?)\s*#*\s*$")
_NUMBERING = re.compile(r"^\s*(?:[0-9]+|[一二三四五六七八九十]+)\s*[.、．)）]\s*")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)、])\s+(.*)$")
_SOURCE = re.compile(r"出处\s*[:：]\s*(.*?)\s*(?=把握程度|$)")
_CONFIDENCE = re.compile(r"把握程度\s*[:：]\s*([^\s;；,，、。）)]*)")
_SEPARATORS = " \t;；,，、。()（）"
_EXCERPT_CHARS = 20


@dataclass(frozen=True, slots=True)
class BriefCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _normalize_heading(raw: str) -> str:
    return _NUMBERING.sub("", raw.strip()).strip().rstrip("：:").strip()


def _split_sections(text: str) -> tuple[list[str], dict[str, str]]:
    """返回 (按出现顺序的二级标题列表, {标题: 首次出现的正文})；代码围栏里的 `##` 不算标题。"""
    order: list[str] = []
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _H2.match(line)
        if heading is not None:
            current = _normalize_heading(heading.group(1))
            order.append(current)
            bodies.setdefault(current, [])
            continue
        if current is not None:
            # 重复出现的章节只累积第一处：`bodies` 已有键时，后面的正文也并进去会掩盖问题，
            # 所以只在「本标题是首次出现」时收集。
            if order.count(current) == 1:
                bodies[current].append(line)
    return order, {name: "\n".join(lines).strip() for name, lines in bodies.items()}


def _fact_items(body: str) -> list[str]:
    items: list[list[str]] = []
    for line in body.splitlines():
        bullet = _BULLET.match(line)
        if bullet is not None:
            items.append([bullet.group(1).strip()])
        elif items and line.strip():
            items[-1].append(line.strip())
    return [" ".join(parts) for parts in items]


def _check_fact(index: int, item: str) -> tuple[list[str], bool]:
    """返回 (这一条的错误, 是否为低把握)。"""
    label = f"关键事实第 {index} 条「{item[:_EXCERPT_CHARS]}」"
    errors: list[str] = []
    source = _SOURCE.search(item)
    if source is None or not source.group(1).strip(_SEPARATORS):
        errors.append(f"{label}缺少出处（格式：出处：<URL 或文献>）")
    confidence = _CONFIDENCE.search(item)
    low = False
    if confidence is None:
        errors.append(f"{label}缺少把握程度（格式：把握程度：高/中/低）")
    elif confidence.group(1) not in CONFIDENCE_VALUES:
        errors.append(f"{label}的把握程度必须是 高/中/低，收到「{confidence.group(1)}」")
    else:
        low = confidence.group(1) == "低"
    return errors, low


def check(text: str | None) -> BriefCheck:
    if text is None or not text.strip():
        return BriefCheck(errors=[f"{BRIEF_PATH} 还不存在，或者是空的。"])
    order, bodies = _split_sections(text)
    errors: list[str] = []
    warnings: list[str] = []

    for name in SECTIONS:
        if name not in bodies:
            errors.append(f"缺少章节「{name}」（二级标题 `## {name}`）")
        elif not bodies[name]:
            errors.append(f"章节「{name}」是空的")

    facts_body = bodies.get(FACTS_SECTION)
    if facts_body:
        items = _fact_items(facts_body)
        if not items:
            errors.append(
                f"章节「{FACTS_SECTION}」没有任何列表项"
                "（每条事实写成 `- 事实（出处：…；把握程度：高/中/低）`）"
            )
        low_count = 0
        for index, item in enumerate(items, start=1):
            item_errors, low = _check_fact(index, item)
            errors += item_errors
            low_count += low
        if low_count:
            warnings.append(f"有 {low_count} 条关键事实的把握程度是「低」：补充证据，或者删掉")

    known = [name for name in order if name in SECTIONS]
    if known != sorted(known, key=SECTIONS.index):
        warnings.append(f"章节顺序与约定不一致（约定顺序：{'、'.join(SECTIONS)}）")
    for name in dict.fromkeys(order):
        if name not in SECTIONS:
            warnings.append(f"有约定之外的章节「{name}」")
        elif order.count(name) > 1:
            warnings.append(f"章节「{name}」出现了多次，只检查了第一处")
    risk = bodies.get(RISK_SECTION)
    if risk and len(risk) < MIN_RISK_CHARS:
        warnings.append(f"章节「{RISK_SECTION}」只有 {len(risk)} 字，太简略")
    return BriefCheck(errors=errors, warnings=warnings)


def check_workspace(workdir: Path | str) -> BriefCheck:
    """读工作区里的 `topic/brief.md` 并检查；文件缺失、不是 UTF-8 都作为错误返回，不抛异常。"""
    try:
        text = files.read_bytes(workdir, BRIEF_PATH).decode("utf-8")
    except FileNotFoundError:
        return check(None)
    except UnicodeDecodeError:
        return BriefCheck(errors=[f"{BRIEF_PATH} 不是合法的 UTF-8 文本。"])
    return check(text)
