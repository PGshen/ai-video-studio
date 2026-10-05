"""从 `concept/brief.md` 的「目标时长」章节读出秒数（`concept` 与 `beatsheet` 共用）。"""

from __future__ import annotations

import re

_PATTERN = re.compile(
    r"(?<![\d.\-])(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>分钟|分|min|minutes?|秒钟|秒|sec|seconds?|s)(?![A-Za-z])",
    re.IGNORECASE,
)
_MINUTE_UNITS = ("分钟", "分", "min", "minute", "minutes")


def parse_target_seconds(text: str) -> float | None:
    """第一个"数字 + 单位"换成秒；没有单位、没有数字或结果不为正返回 `None`。"""
    match = _PATTERN.search(text)
    if match is None:
        return None
    value = float(match.group("value"))
    if match.group("unit").lower() in _MINUTE_UNITS:
        seconds = value * 60.0
        start = match.end() + len(text[match.end() :]) - len(text[match.end() :].lstrip())
        rest = _PATTERN.match(text, start)  # "1分30秒": the seconds follow the minutes
        if rest is not None and rest.group("unit").lower() not in _MINUTE_UNITS:
            seconds += float(rest.group("value"))
    else:
        seconds = value
    return seconds if seconds > 0 else None


_H2 = re.compile(r"^##\s+(.*?)\s*#*\s*$")
_NUMBERING = re.compile(r"^\s*(?:[0-9]+|[一二三四五六七八九十]+)\s*[.、．)）]\s*")


def target_seconds_from_brief(text: str, section: str = "目标时长") -> float | None:
    """`brief.md` 里名为 `section` 的二级章节的正文 → 秒；没有该章节或读不出返回 `None`。"""
    body: list[str] | None = None
    for line in text.splitlines():
        heading = _H2.match(line)
        if heading:
            if body is not None:
                break
            if _NUMBERING.sub("", heading.group(1)).strip() == section:
                body = []
        elif body is not None:
            body.append(line)
    return parse_target_seconds("\n".join(body)) if body is not None else None
