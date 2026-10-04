"""风格的目录存储：正式版本、草稿、原子保存（ADR 0019；计划 style-library T2）。

- 正式版本 `<data>/styles/<id>/`；保存时先写临时目录再 rename 替换，失败时旧版本不变。
- 草稿 `<data>/style-drafts/<id>/`：用户编辑和 agent 对话都只改草稿；`save_draft` 校验通过后
  才覆盖正式版本，`discard_draft` 丢弃草稿。从未保存过的新建风格只有草稿，不出现在列表里。
- 读取目录一律不跟随符号链接；草稿里出现符号链接、顶层多余文件、非 UTF-8 内容等在保存时
  作为校验错误报告，不会被静默复制。

没有任何数据库依赖；错误用中文消息，由 API 层映射成 HTTP 状态码。
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

from studio.styles.layout import (
    ENTRY_NAME,
    draft_dir,
    is_valid_style_id,
    style_dir,
    styles_root,
)
from studio.styles.validate import (
    MAX_FILE_CHARS,
    StyleFiles,
    is_plain_file_name,
    parse_frontmatter,
    set_frontmatter_fields,
    split_style_path,
    validate_style_files,
)

logger = logging.getLogger(__name__)

UNCATEGORIZED: Final = "未分类"
ENTRY_TEMPLATE: Final = """---
name: 新风格
description: 一句话说明这套风格的特点和适用场景
category: 未分类
---

# 新风格

在这里写这套风格的入口说明：列出每个文件的用途，以及选题、叙事、动画各阶段什么时候读取。
"""
_IGNORED_FILES: Final = {".DS_Store"}
_MAX_READ_BYTES: Final = MAX_FILE_CHARS * 4


class StyleNotFoundError(LookupError):
    """风格（或草稿里的文件）不存在。"""


class StyleValidationError(ValueError):
    """内容不合法（API 映射为 422）；`errors` 逐条列出问题。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("；".join(errors))
        self.errors = errors


class DuplicateStyleNameError(RuntimeError):
    """名称（去首尾空白后）与别的风格重复（API 映射为 409）。"""


class StyleExistsError(RuntimeError):
    """目录已存在且没有要求覆盖。"""


class StylePathError(ValueError):
    """草稿文件路径不合法（API 映射为 400）。"""


@dataclass(frozen=True, slots=True)
class StyleSummary:
    """列表用；`has_draft` 表示有未保存的草稿。"""

    id: str
    name: str
    category: str
    description: str | None
    reference_count: int
    exemplar_count: int
    modified_at: datetime
    has_draft: bool


@dataclass(frozen=True, slots=True)
class StyleDetail:
    id: str
    name: str
    category: str
    description: str | None
    files: StyleFiles
    modified_at: datetime


@dataclass(frozen=True, slots=True)
class DraftStatus:
    id: str
    is_new: bool
    """从未保存过：正式版本不存在。"""
    dirty: bool
    """草稿内容与正式版本不同（新建的草稿总是 `True`）。"""
    files: list[str]
    """草稿里的常规文件，相对路径，已排序。"""


# ---- 目录读写 -----------------------------------------------------------


def _read_tree(root: Path) -> tuple[StyleFiles, list[str]]:
    """读出目录下的全部文本文件和读取时发现的问题；不跟随符号链接，忽略 `.DS_Store`。"""
    files: StyleFiles = {}
    problems: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        for name in list(dirnames):
            if (base / name).is_symlink():
                dirnames.remove(name)
                problems.append(f"不允许符号链接：{(base / name).relative_to(root).as_posix()}")
        for name in filenames:
            if name in _IGNORED_FILES:
                continue
            full = base / name
            rel = full.relative_to(root).as_posix()
            if full.is_symlink() or not full.is_file():
                problems.append(f"不允许符号链接或特殊文件：{rel}")
                continue
            if full.stat().st_size > _MAX_READ_BYTES:
                problems.append(f"{rel} 过长（上限 {MAX_FILE_CHARS} 字符）")
                continue
            try:
                files[rel] = full.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                problems.append(f"{rel} 不是 UTF-8 文本")
    return files, problems


def _write_tree(root: Path, files: StyleFiles) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    root.mkdir(parents=True, exist_ok=True)


def _swap(tmp: Path, final: Path) -> None:
    """用 `tmp` 替换 `final`；中途失败时把旧版本放回去。"""
    backup: Path | None = None
    if final.exists():
        backup = final.with_name(f".{final.name}.old-{uuid4().hex}")
        final.rename(backup)
    try:
        tmp.rename(final)
    except BaseException:
        if backup is not None:
            backup.rename(final)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


def _install(tmp_files: StyleFiles, final: Path) -> None:
    """把一份内容原子地装到 `final`：先写同级的临时目录，再 `_swap`。"""
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(f".{final.name}.tmp-{uuid4().hex}")
    try:
        _write_tree(tmp, tmp_files)
        _swap(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _mtime(root: Path) -> datetime:
    times = [p.stat().st_mtime for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    return datetime.fromtimestamp(max(times, default=root.stat().st_mtime), tz=UTC)


def _saved_path(data_dir: Path | str, style_id: str) -> Path:
    if not is_valid_style_id(style_id):
        raise StyleNotFoundError(style_id)
    return style_dir(data_dir, style_id)


def _draft_path(data_dir: Path | str, style_id: str) -> Path:
    if not is_valid_style_id(style_id):
        raise StyleNotFoundError(style_id)
    return draft_dir(data_dir, style_id)


def _detail(style_id: str, files: StyleFiles, modified_at: datetime) -> StyleDetail:
    meta = parse_frontmatter(files.get(ENTRY_NAME, "")) or {}
    return StyleDetail(
        id=style_id,
        name=meta.get("name", "").strip() or style_id,
        category=meta.get("category", "").strip() or UNCATEGORIZED,
        description=meta.get("description", "").strip() or None,
        files=files,
        modified_at=modified_at,
    )


def _name_of(files: StyleFiles) -> str:
    return (parse_frontmatter(files.get(ENTRY_NAME, "")) or {}).get("name", "").strip()


# ---- 正式版本 -----------------------------------------------------------


def list_styles(data_dir: Path | str) -> list[StyleSummary]:
    """按分类、名称排序；坏目录（没有 `STYLE.md`、frontmatter 不合法）跳过并记警告。"""
    root = styles_root(data_dir)
    if not root.is_dir():
        return []
    summaries: list[StyleSummary] = []
    for child in sorted(root.iterdir()):
        if not is_valid_style_id(child.name) or child.is_symlink() or not child.is_dir():
            continue
        files, _problems = _read_tree(child)
        meta = parse_frontmatter(files.get(ENTRY_NAME, ""))
        if meta is None or not meta.get("name", "").strip():
            logger.warning("风格目录无法识别，已跳过：%s", child)
            continue
        detail = _detail(child.name, files, _mtime(child))
        summaries.append(
            StyleSummary(
                id=detail.id,
                name=detail.name,
                category=detail.category,
                description=detail.description,
                reference_count=sum(1 for p in files if p.startswith("references/")),
                exemplar_count=sum(1 for p in files if p.startswith("exemplars/")),
                modified_at=detail.modified_at,
                has_draft=draft_dir(data_dir, child.name).is_dir(),
            )
        )
    return sorted(summaries, key=lambda s: (s.category, s.name))


def get_style(data_dir: Path | str, style_id: str) -> StyleDetail:
    path = _saved_path(data_dir, style_id)
    if not path.is_dir():
        raise StyleNotFoundError(style_id)
    files, _problems = _read_tree(path)
    if ENTRY_NAME not in files:
        raise StyleNotFoundError(style_id)
    return _detail(style_id, files, _mtime(path))


def read_style_files(data_dir: Path | str, style_id: str) -> StyleFiles:
    """正式版本的全部文件（创建项目时复制进 `style/` 用）。"""
    return get_style(data_dir, style_id).files


def style_exists(data_dir: Path | str, style_id: str) -> bool:
    return is_valid_style_id(style_id) and style_dir(data_dir, style_id).is_dir()


def _ensure_unique_name(data_dir: Path | str, name: str, *, except_id: str | None) -> None:
    for existing in list_styles(data_dir):
        if existing.id != except_id and existing.name.strip() == name:
            raise DuplicateStyleNameError(f"已有同名的风格：{name}")


def import_style(
    data_dir: Path | str,
    files: StyleFiles,
    *,
    style_id: str | None = None,
    overwrite: bool = False,
) -> StyleDetail:
    """校验后直接写成正式版本（迁移旧表、导入脚本用）。`style_id` 为空时生成新 id；
    目录已存在且没有 `overwrite` 时抛 `StyleExistsError`；名称与别的风格重复抛
    `DuplicateStyleNameError`；内容不合法抛 `StyleValidationError`，什么都不写。"""
    errors = validate_style_files(files)
    if errors:
        raise StyleValidationError(errors)
    new_id = style_id if style_id is not None else uuid4().hex
    if not is_valid_style_id(new_id):
        raise StyleValidationError([f"风格 id 不合法：{new_id!r}"])
    if style_dir(data_dir, new_id).exists() and not overwrite:
        raise StyleExistsError(new_id)
    _ensure_unique_name(data_dir, _name_of(files), except_id=new_id)
    _install(files, style_dir(data_dir, new_id))
    return get_style(data_dir, new_id)


def duplicate_style(data_dir: Path | str, style_id: str) -> StyleDetail:
    """复制成独立的一份，名称是「原名（副本）」，已占用时依次「（副本 2）」「（副本 3）」…"""
    source = get_style(data_dir, style_id)
    taken = {s.name.strip() for s in list_styles(data_dir)}
    candidate, n = f"{source.name}（副本）", 1
    while candidate in taken:
        n += 1
        candidate = f"{source.name}（副本 {n}）"
    files = dict(source.files)
    files[ENTRY_NAME] = set_frontmatter_fields(files[ENTRY_NAME], {"name": candidate})
    return import_style(data_dir, files)


def delete_style(data_dir: Path | str, style_id: str) -> None:
    """删除正式版本和草稿；两者都不存在时抛 `StyleNotFoundError`。"""
    saved, draft = _saved_path(data_dir, style_id), _draft_path(data_dir, style_id)
    if not saved.exists() and not draft.exists():
        raise StyleNotFoundError(style_id)
    shutil.rmtree(saved, ignore_errors=True)
    shutil.rmtree(draft, ignore_errors=True)


# ---- 草稿 ---------------------------------------------------------------


def create_new_draft(data_dir: Path | str) -> str:
    """新建风格：生成带模板的草稿，返回新 id；保存之前不出现在列表里。"""
    style_id = uuid4().hex
    _install({ENTRY_NAME: ENTRY_TEMPLATE}, draft_dir(data_dir, style_id))
    return style_id


def open_draft(data_dir: Path | str, style_id: str) -> DraftStatus:
    """没有草稿就从正式版本复制一份，已有则原样返回（幂等）。"""
    draft = _draft_path(data_dir, style_id)
    if not draft.is_dir():
        saved = _saved_path(data_dir, style_id)
        if not saved.is_dir():
            raise StyleNotFoundError(style_id)
        files, _problems = _read_tree(saved)
        _install(files, draft)
    return draft_status(data_dir, style_id)


def draft_status(data_dir: Path | str, style_id: str) -> DraftStatus:
    draft = _draft_path(data_dir, style_id)
    if not draft.is_dir():
        raise StyleNotFoundError(style_id)
    files, problems = _read_tree(draft)
    saved = _saved_path(data_dir, style_id)
    is_new = not saved.is_dir()
    dirty = True if is_new or problems else _read_tree(saved)[0] != files
    return DraftStatus(id=style_id, is_new=is_new, dirty=dirty, files=sorted(files))


def _draft_file(data_dir: Path | str, style_id: str, relpath: str) -> Path:
    """草稿里一个文件的路径：只允许 `STYLE.md` 和 `references|exemplars/<普通文件名>`，且路径上
    不能有符号链接（防止通过链接读写草稿以外的文件）。"""
    draft = _draft_path(data_dir, style_id)
    if not draft.is_dir():
        raise StyleNotFoundError(style_id)
    parts = split_style_path(relpath)
    if relpath != ENTRY_NAME and (parts is None or not is_plain_file_name(parts[1])):
        raise StylePathError(f"路径不合法：{relpath!r}")
    target = draft / relpath
    for candidate in (draft, *[draft / part for part in Path(relpath).parts[:-1]], target):
        if candidate.is_symlink():
            raise StylePathError(f"不允许符号链接：{relpath!r}")
    return target


def read_draft_file(data_dir: Path | str, style_id: str, relpath: str) -> str:
    target = _draft_file(data_dir, style_id, relpath)
    if not target.is_file():
        raise StyleNotFoundError(relpath)
    try:
        return target.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StyleValidationError([f"{relpath} 不是 UTF-8 文本"]) from exc


def write_draft_file(data_dir: Path | str, style_id: str, relpath: str, text: str) -> None:
    target = _draft_file(data_dir, style_id, relpath)
    if len(text) > MAX_FILE_CHARS:
        raise StyleValidationError([f"{relpath} 过长（上限 {MAX_FILE_CHARS} 字符）"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def delete_draft_file(data_dir: Path | str, style_id: str, relpath: str) -> None:
    target = _draft_file(data_dir, style_id, relpath)
    if not target.is_file():
        raise StyleNotFoundError(relpath)
    target.unlink()


def discard_draft(data_dir: Path | str, style_id: str) -> None:
    """丢弃草稿；从未保存的新建风格因此整个消失。风格和草稿都不存在时抛 `StyleNotFoundError`。"""
    draft = _draft_path(data_dir, style_id)
    if draft.is_dir():
        shutil.rmtree(draft)
    elif not _saved_path(data_dir, style_id).is_dir():
        raise StyleNotFoundError(style_id)


def validate_draft(data_dir: Path | str, style_id: str) -> list[str]:
    """草稿当前的全部问题（读取时发现的 + 内容校验），空列表表示可以保存。"""
    draft = _draft_path(data_dir, style_id)
    if not draft.is_dir():
        raise StyleNotFoundError(style_id)
    files, problems = _read_tree(draft)
    return [*problems, *validate_style_files(files)]


def save_draft(data_dir: Path | str, style_id: str) -> StyleDetail:
    """校验草稿，通过后原子地覆盖（或新建）正式版本并删除草稿。

    不合法抛 `StyleValidationError`、名称与别的风格重复抛 `DuplicateStyleNameError`；
    任何失败都不改正式版本，草稿保持原样。"""
    draft = _draft_path(data_dir, style_id)
    if not draft.is_dir():
        raise StyleNotFoundError(style_id)
    files, problems = _read_tree(draft)
    errors = [*problems, *validate_style_files(files)]
    if errors:
        raise StyleValidationError(errors)
    _ensure_unique_name(data_dir, _name_of(files), except_id=style_id)
    _install(files, style_dir(data_dir, style_id))
    shutil.rmtree(draft, ignore_errors=True)
    return get_style(data_dir, style_id)


__all__ = [
    "ENTRY_TEMPLATE",
    "UNCATEGORIZED",
    "DraftStatus",
    "DuplicateStyleNameError",
    "StyleDetail",
    "StyleExistsError",
    "StyleNotFoundError",
    "StylePathError",
    "StyleSummary",
    "StyleValidationError",
    "create_new_draft",
    "delete_draft_file",
    "delete_style",
    "discard_draft",
    "draft_status",
    "duplicate_style",
    "get_style",
    "import_style",
    "list_styles",
    "open_draft",
    "read_draft_file",
    "read_style_files",
    "save_draft",
    "style_exists",
    "validate_draft",
    "write_draft_file",
]
