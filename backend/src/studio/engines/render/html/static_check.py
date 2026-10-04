"""镜头脚本的确定性静态检查与字号警告（设计 §6.3）。

先剥离注释（保留换行，行号不漂移；字符串内容保留，所以字符串里的 `//` 不会被当成注释，
代码里写出的外部 URL 仍会被报告），再逐行匹配禁用 API。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MIN_FONT_PX = 24

_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Math\.random"), "禁止 Math.random（不确定）：请自己写带种子的伪随机函数"),
    (re.compile(r"\bDate\b"), "禁止 Date（不确定）：时间只能来自 lt / env"),
    (re.compile(r"performance\.now"), "禁止 performance.now"),
    (re.compile(r"requestAnimationFrame"), "禁止 requestAnimationFrame：draw 必须是 lt 的纯函数"),
    (re.compile(r"\bsetTimeout\b|\bsetInterval\b"), "禁止 setTimeout/setInterval"),
    (re.compile(r"\bfetch\b|XMLHttpRequest"), "禁止网络访问（fetch/XMLHttpRequest）"),
    (re.compile(r"https?://"), "禁止外部 URL"),
    (re.compile(r"\beval\b|new\s+Function"), "禁止 eval / new Function"),
]
_FONT_PX = re.compile(r"(\d+(?:\.\d+)?)px")


@dataclass(frozen=True, slots=True)
class StaticIssue:
    path: str
    line: int
    message: str


def _script_files(workdir: Path) -> list[Path]:
    files = sorted((workdir / "animation" / "scenes").glob("*.js"))
    files += sorted((workdir / "animation" / "lib").glob("*.js"))
    global_js = workdir / "animation" / "global.js"
    if global_js.is_file():
        files.append(global_js)
    return files


def strip_comments(source: str) -> str:
    """把 JS 注释换成空白（换行保留），字符串与模板字面量原样保留。"""
    out: list[str] = []
    i, n = 0, len(source)
    quote: str | None = None
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if ch == quote or (ch == "\n" and quote != "`"):
                quote = None
            i += 1
        elif ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
        elif ch == "/" and nxt == "/":
            while i < n and source[i] != "\n":
                i += 1
        elif ch == "/" and nxt == "*":
            end = source.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append("".join("\n" if c == "\n" else " " for c in source[i:end]))
            i = end
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def static_check(workdir: Path) -> list[StaticIssue]:
    issues: list[StaticIssue] = []
    for path in _script_files(workdir):
        relpath = path.relative_to(workdir).as_posix()
        for number, line in enumerate(
            strip_comments(path.read_text(encoding="utf-8")).splitlines(), 1
        ):
            for pattern, message in _RULES:
                if pattern.search(line):
                    issues.append(StaticIssue(relpath, number, message))
    return issues


def font_size_warnings(workdir: Path) -> list[StaticIssue]:
    warnings: list[StaticIssue] = []
    for path in _script_files(workdir):
        relpath = path.relative_to(workdir).as_posix()
        for number, line in enumerate(
            strip_comments(path.read_text(encoding="utf-8")).splitlines(), 1
        ):
            if "font" not in line:
                continue
            small = [m.group(1) for m in _FONT_PX.finditer(line) if float(m.group(1)) < MIN_FONT_PX]
            if small:
                warnings.append(
                    StaticIssue(
                        relpath,
                        number,
                        f"字面量字号 {small[0]}px 小于 {MIN_FONT_PX}px：除非纯装饰否则视频里不可读",
                    )
                )
    return warnings
