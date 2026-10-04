"""风格目录内容的校验与 frontmatter 解析（纯函数，没有 IO）。

内容用 `StyleFiles`（相对路径 → 文本）表示，路径形如 `STYLE.md`、`references/x.md`、
`exemplars/y.json`。规则从旧的 `db.repo.style_presets.validate_style_preset` 迁移而来
（ADR 0011），并新增：顶层只允许入口和两个子目录。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Final

from studio.styles.layout import ENTRY_NAME, EXEMPLARS_DIR, REFERENCES_DIR

StyleFiles = dict[str, str]
"""`{相对路径: 文本}`。"""

MAX_FILE_CHARS: Final = 200_000
MAX_FILES_PER_DIR: Final = 30
MAX_NAME_CHARS: Final = 100
MAX_FILE_NAME_CHARS: Final = 80

_FILE_NAME = re.compile(r"^[\w.\-]+$")
_ENTRY_REFERENCE = re.compile(r"\b(references|exemplars)/([\w.\-]+)")
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_SUFFIXES: Final = {REFERENCES_DIR: (".md",), EXEMPLARS_DIR: (".json", ".md")}


def parse_frontmatter(content: str) -> dict[str, str] | None:
    """解析 `STYLE.md` 开头的 `---` 块里的 `key: value` 行；没有完整的块时返回 `None`。"""
    match = _FRONTMATTER.match(content)
    if match is None:
        return None
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote, value = value[0], value[1:-1]
            if quote == '"':  # YAML 双引号字符串里 \" 和 \\ 是转义
                value = re.sub(r'\\(["\\])', r"\1", value)
        result[key.strip()] = value
    return result


def _split(path: str) -> tuple[str, str] | None:
    """`references/x.md` → `("references", "x.md")`；入口和不允许的路径返回 `None`。"""
    for directory in (REFERENCES_DIR, EXEMPLARS_DIR):
        prefix = f"{directory}/"
        if path.startswith(prefix):
            return directory, path[len(prefix) :]
    return None


def _validate_entry(content: str, errors: list[str]) -> None:
    frontmatter = parse_frontmatter(content)
    if frontmatter is None:
        errors.append("STYLE.md 必须以 frontmatter 开头（--- 包起来的 name、description）")
    else:
        for key in ("name", "description"):
            if not frontmatter.get(key, "").strip():
                errors.append(f"STYLE.md 的 frontmatter 缺少非空的 {key}")
        name = frontmatter.get("name", "").strip()
        if len(name) > MAX_NAME_CHARS:
            errors.append(f"名称过长（上限 {MAX_NAME_CHARS} 字）")
    if len(content) > MAX_FILE_CHARS:
        errors.append(f"STYLE.md 过长（上限 {MAX_FILE_CHARS} 字符）")


def _validate_file(directory: str, name: str, text: str, errors: list[str]) -> None:
    label = f"{directory}/{name}"
    if (
        not name
        or len(name) > MAX_FILE_NAME_CHARS
        or name.startswith(".")
        or _FILE_NAME.match(name) is None
    ):
        errors.append(
            f"文件名不合法：{label!r}（只允许字母、数字、下划线、点和连字符，不能以点开头）"
        )
        return
    suffixes = _SUFFIXES[directory]
    if not name.endswith(suffixes):
        errors.append(f"{label} 的扩展名只能是 {' / '.join(suffixes)}")
    if len(text) > MAX_FILE_CHARS:
        errors.append(f"{label} 过长（上限 {MAX_FILE_CHARS} 字符）")
    if name.endswith(".json"):
        try:
            json.loads(text)
        except ValueError:
            errors.append(f"{label} 不是合法的 JSON")


def validate_style_files(files: Mapping[str, str]) -> list[str]:
    """返回中文错误列表，空列表表示合法。纯函数。"""
    errors: list[str] = []
    counts = {REFERENCES_DIR: 0, EXEMPLARS_DIR: 0}
    existing: dict[str, set[str]] = {REFERENCES_DIR: set(), EXEMPLARS_DIR: set()}

    for path, text in files.items():
        if path == ENTRY_NAME:
            continue
        parts = _split(path)
        if parts is None:
            errors.append(
                f"不允许的路径：{path!r}（只能有 STYLE.md、references/ 和 exemplars/ 下的文件）"
            )
            continue
        directory, name = parts
        counts[directory] += 1
        existing[directory].add(name)
        _validate_file(directory, name, text, errors)

    for directory, count in counts.items():
        if count > MAX_FILES_PER_DIR:
            errors.append(f"{directory}/ 最多 {MAX_FILES_PER_DIR} 个文件，现在有 {count} 个")

    entry = files.get(ENTRY_NAME)
    if entry is None:
        errors.append("缺少入口文件 STYLE.md")
        return errors
    _validate_entry(entry, errors)

    reported: set[str] = set()
    for directory, raw_name in _ENTRY_REFERENCE.findall(entry):
        # 句末的标点（`references/x.md.`、`x.md-`）不是文件名的一部分。
        file_name = raw_name.rstrip(".-")
        path = f"{directory}/{file_name}"
        if file_name not in existing[directory] and path not in reported:
            reported.add(path)
            errors.append(f"STYLE.md 引用了不存在的文件：{path}")
    return errors
