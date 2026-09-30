"""`style_presets` 仓储：风格库（设计 §3.1、§5.5；计划 M5 T2，决策 D1）。

一套风格是「skill 形态的目录」：

- `content`：入口 `STYLE.md` 全文，必须有 `name`/`description` 的 frontmatter；
- `reference_files`（对外叫 `references`）：`[{name, text}]`，落盘到 `style/references/<name>`；
- `exemplars`：`[{name, text}]`，金样本，落盘到 `style/exemplars/<name>`。

所有写入都经过 `validate_style_preset`，库里不会有不合法的预设（导入脚本也一样）。
校验是纯函数，没有 IO。读取不校验：迁移前写入的旧行（没有 frontmatter）照样能读。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from studio.db.engine import session_scope
from studio.db.models import StylePreset

MAX_FILE_CHARS: Final = 200_000
MAX_FILES_PER_DIR: Final = 30
MAX_NAME_CHARS: Final = 100
MAX_FILE_NAME_CHARS: Final = 80

_FILE_NAME = re.compile(r"^[\w.\-]+$")
_ENTRY_REFERENCE = re.compile(r"\b(references|exemplars)/([\w.\-]+)")
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_REFERENCE_SUFFIXES: Final = (".md",)
_EXEMPLAR_SUFFIXES: Final = (".json", ".md")


class StylePresetValidationError(ValueError):
    """预设不合法（API 映射为 422）；消息里逐条列出问题。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("；".join(errors))
        self.errors = errors


class StylePresetNotFoundError(LookupError):
    pass


class DuplicateStylePresetError(RuntimeError):
    """名字（去首尾空白后）与已有预设重复（API 映射为 409）。"""


@dataclass(frozen=True, slots=True)
class StyleFile:
    name: str
    text: str


@dataclass(frozen=True, slots=True)
class StylePresetValue:
    id: str
    name: str
    category: str
    description: str | None
    content: str
    references: list[StyleFile]
    exemplars: list[StyleFile]
    created_at: datetime


# ---- 校验 ---------------------------------------------------------------


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
            value = value[1:-1]
        result[key.strip()] = value
    return result


def _validate_files(
    directory: str, files: list[StyleFile], suffixes: tuple[str, ...], errors: list[str]
) -> None:
    if len(files) > MAX_FILES_PER_DIR:
        errors.append(f"{directory}/ 最多 {MAX_FILES_PER_DIR} 个文件，现在有 {len(files)} 个")
    seen: set[str] = set()
    for file in files:
        label = f"{directory}/{file.name}"
        if (
            not file.name
            or len(file.name) > MAX_FILE_NAME_CHARS
            or file.name.startswith(".")
            or _FILE_NAME.match(file.name) is None
        ):
            errors.append(
                f"文件名不合法：{label!r}（只允许字母、数字、下划线、点和连字符，不能以点开头）"
            )
            continue
        if file.name in seen:
            errors.append(f"文件名重复：{label}")
        seen.add(file.name)
        if not file.name.endswith(suffixes):
            errors.append(f"{label} 的扩展名只能是 {' / '.join(suffixes)}")
        if len(file.text) > MAX_FILE_CHARS:
            errors.append(f"{label} 过长（上限 {MAX_FILE_CHARS} 字符）")
        if file.name.endswith(".json"):
            try:
                json.loads(file.text)
            except ValueError:
                errors.append(f"{label} 不是合法的 JSON")


def validate_style_preset(
    *,
    name: str,
    content: str,
    references: list[StyleFile],
    exemplars: list[StyleFile],
) -> list[str]:
    """返回中文错误列表，空列表表示合法。纯函数。"""
    errors: list[str] = []
    if not name.strip():
        errors.append("名称不能为空")
    elif len(name.strip()) > MAX_NAME_CHARS:
        errors.append(f"名称过长（上限 {MAX_NAME_CHARS} 字）")

    frontmatter = parse_frontmatter(content)
    if frontmatter is None:
        errors.append("STYLE.md 必须以 frontmatter 开头（--- 包起来的 name、description）")
    else:
        for key in ("name", "description"):
            if not frontmatter.get(key, "").strip():
                errors.append(f"STYLE.md 的 frontmatter 缺少非空的 {key}")
    if len(content) > MAX_FILE_CHARS:
        errors.append(f"STYLE.md 过长（上限 {MAX_FILE_CHARS} 字符）")

    _validate_files("references", references, _REFERENCE_SUFFIXES, errors)
    _validate_files("exemplars", exemplars, _EXEMPLAR_SUFFIXES, errors)

    existing = {
        "references": {f.name for f in references},
        "exemplars": {f.name for f in exemplars},
    }
    reported: set[str] = set()
    for directory, file_name in _ENTRY_REFERENCE.findall(content):
        path = f"{directory}/{file_name}"
        if file_name not in existing[directory] and path not in reported:
            reported.add(path)
            errors.append(f"STYLE.md 引用了不存在的文件：{path}")
    return errors


# ---- 读写 ---------------------------------------------------------------


def _files(raw: list[Any] | None) -> list[StyleFile]:
    return [StyleFile(name=item["name"], text=item["text"]) for item in raw or []]


def _raw(files: list[StyleFile]) -> list[dict[str, str]]:
    return [{"name": f.name, "text": f.text} for f in files]


def _to_value(row: StylePreset) -> StylePresetValue:
    return StylePresetValue(
        id=row.id,
        name=row.name,
        category=row.category,
        description=row.description,
        content=row.content,
        references=_files(row.reference_files),
        exemplars=_files(row.exemplars),
        # SQLite 读回来的时间没有时区信息，库里存的是 UTC（db/models.py）。
        created_at=row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC),
    )


def _check(
    name: str, content: str, references: list[StyleFile], exemplars: list[StyleFile]
) -> None:
    errors = validate_style_preset(
        name=name, content=content, references=references, exemplars=exemplars
    )
    if errors:
        raise StylePresetValidationError(errors)


def _ensure_unique_name(db: Session, name: str, *, except_id: str | None = None) -> None:
    for row in db.scalars(select(StylePreset)):
        if row.id != except_id and row.name.strip() == name:
            raise DuplicateStylePresetError(f"已有同名的风格：{name}")


def create_style_preset(
    engine: Engine,
    *,
    name: str,
    category: str,
    description: str | None,
    content: str,
    references: list[StyleFile],
    exemplars: list[StyleFile],
) -> StylePresetValue:
    """校验后新建；名字重复抛 `DuplicateStylePresetError`，不合法抛 `StylePresetValidationError`。
    `description` 为空时取入口 frontmatter 里的 description。"""
    name = name.strip()
    _check(name, content, references, exemplars)
    if description is None:
        description = (parse_frontmatter(content) or {}).get("description")
    with session_scope(engine) as db:
        _ensure_unique_name(db, name)
        row = StylePreset(
            name=name,
            category=category.strip(),
            description=description,
            content=content,
            reference_files=_raw(references),
            exemplars=_raw(exemplars),
        )
        db.add(row)
        db.flush()
        return _to_value(row)


def get_style_preset(engine: Engine, preset_id: str) -> StylePresetValue | None:
    with session_scope(engine) as db:
        row = db.get(StylePreset, preset_id)
        return _to_value(row) if row is not None else None


def list_style_presets(engine: Engine) -> list[StylePresetValue]:
    """按分类、名称排序。"""
    with session_scope(engine) as db:
        rows = db.scalars(select(StylePreset)).all()
        return sorted((_to_value(r) for r in rows), key=lambda v: (v.category, v.name))


def update_style_preset(
    engine: Engine,
    preset_id: str,
    *,
    name: str | None = None,
    category: str | None = None,
    description: str | None = None,
    content: str | None = None,
    references: list[StyleFile] | None = None,
    exemplars: list[StyleFile] | None = None,
) -> StylePresetValue:
    """只改给了值的字段；列表字段整体替换。校验的是合并后的结果，不合法时什么都不写。"""
    with session_scope(engine) as db:
        row = db.get(StylePreset, preset_id)
        if row is None:
            raise StylePresetNotFoundError(preset_id)
        new_name = row.name if name is None else name.strip()
        new_content = row.content if content is None else content
        new_refs = _files(row.reference_files) if references is None else references
        new_exemplars = _files(row.exemplars) if exemplars is None else exemplars
        _check(new_name, new_content, new_refs, new_exemplars)
        _ensure_unique_name(db, new_name, except_id=preset_id)
        row.name = new_name
        row.content = new_content
        row.reference_files = _raw(new_refs)
        row.exemplars = _raw(new_exemplars)
        if category is not None:
            row.category = category.strip()
        if description is not None:
            row.description = description
        db.flush()
        return _to_value(row)


def delete_style_preset(engine: Engine, preset_id: str) -> None:
    with session_scope(engine) as db:
        row = db.get(StylePreset, preset_id)
        if row is None:
            raise StylePresetNotFoundError(preset_id)
        db.delete(row)


def duplicate_style_preset(engine: Engine, preset_id: str) -> StylePresetValue:
    """复制成独立的一份，名字是「原名（副本）」，已占用时依次「（副本 2）」「（副本 3）」…"""
    source = get_style_preset(engine, preset_id)
    if source is None:
        raise StylePresetNotFoundError(preset_id)
    taken = {p.name.strip() for p in list_style_presets(engine)}
    candidate, n = f"{source.name}（副本）", 1
    while candidate in taken:
        n += 1
        candidate = f"{source.name}（副本 {n}）"
    return create_style_preset(
        engine,
        name=candidate,
        category=source.category,
        description=source.description,
        content=source.content,
        references=source.references,
        exemplars=source.exemplars,
    )
