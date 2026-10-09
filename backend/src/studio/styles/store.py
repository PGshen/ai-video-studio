"""风格的目录存储：正式版本、草稿、原子保存（ADR 0019；计划 style-library T2）。

- 正式版本 `<data>/styles/<id>/`；保存时先写临时目录再 rename 替换，失败时旧版本不变。
- 草稿 `<data>/style-drafts/<id>/`：用户编辑和 agent 对话都只改草稿；`save_draft` 校验通过后
  才覆盖正式版本，`discard_draft` 丢弃草稿。从未保存过的新建风格只有草稿：`list_styles` 列出它
  （`is_new`），`list_saved_styles` 不含它。
- `screenshots/`（ADR 0022）存二进制截图：`StyleFiles` 只装文本，读目录时跳过它，截图由
  `studio.styles.screenshots` 和本模块的专用函数处理；它和文本走同一套草稿流程。
- 读取目录一律不跟随符号链接；草稿里出现符号链接、顶层多余文件、非 UTF-8 内容等在保存时
  作为校验错误报告，不会被静默复制。

没有任何数据库依赖；错误用中文消息，由 API 层映射成 HTTP 状态码。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

from studio.styles.layout import (
    ENTRY_NAME,
    EXEMPLARS_DIR,
    REFERENCES_DIR,
    SCREENSHOTS_DIR,
    UPLOADS_DIR,
    draft_dir,
    drafts_root,
    is_valid_style_id,
    style_dir,
    styles_root,
)
from studio.styles.screenshots import (
    MAX_SCREENSHOTS,
    is_screenshot_name,
    list_screenshots,
    renumbered,
    verify_screenshot,
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
_RUNTIME_DIRS: Final = {".claude", ".cache"}
"""运行时自己在工作目录里建的目录（Claude 的 `.claude/`、OpenAI Shell 的 `.cache/tmp`）：
清理时静默删除，不当作多余文件报告。"""
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
    cover: str | None = None
    """第一张截图的文件名（没有截图时为 `None`）；`is_new` 的风格取草稿里的。"""
    is_new: bool = False
    """从未保存过：只有草稿，没有正式版本（列表里标记出来，让它不会成为找不回的孤儿）。"""


@dataclass(frozen=True, slots=True)
class StyleDetail:
    id: str
    name: str
    category: str
    description: str | None
    files: StyleFiles
    modified_at: datetime
    screenshots: list[str] = field(default_factory=list)
    """截图文件名，按显示顺序，第一张是封面。"""


@dataclass(frozen=True, slots=True)
class DraftStatus:
    id: str
    is_new: bool
    """从未保存过：正式版本不存在。"""
    dirty: bool
    """草稿内容与正式版本不同（新建的草稿总是 `True`）。"""
    files: list[str]
    """草稿里的常规文件，相对路径，已排序。"""
    screenshots: list[str] = field(default_factory=list)
    """草稿里的截图文件名，按显示顺序。"""


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
        if base == root and SCREENSHOTS_DIR in dirnames:
            dirnames.remove(SCREENSHOTS_DIR)  # 二进制截图不进 StyleFiles，下面单独检查
        if base == root and UPLOADS_DIR in dirnames:
            dirnames.remove(UPLOADS_DIR)  # 对话附件不属于风格本身（设计 2026-10-09 修订 R1）
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
    problems.extend(list_screenshots(root / SCREENSHOTS_DIR, verify=True)[1])
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


def _copy_screenshots(source: Path, target: Path) -> None:
    names = list_screenshots(source / SCREENSHOTS_DIR)[0]
    if not names:
        return
    (target / SCREENSHOTS_DIR).mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copyfile(source / SCREENSHOTS_DIR / name, target / SCREENSHOTS_DIR / name)


def _install(tmp_files: StyleFiles, final: Path, *, screenshots_from: Path | None = None) -> None:
    """把一份内容原子地装到 `final`：先写同级的临时目录（文本，加上 `screenshots_from` 目录下的
    截图），再 `_swap`。"""
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(f".{final.name}.tmp-{uuid4().hex}")
    try:
        _write_tree(tmp, tmp_files)
        if screenshots_from is not None:
            _copy_screenshots(screenshots_from, tmp)
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


def _screenshots_of(root: Path) -> list[str]:
    return list_screenshots(root / SCREENSHOTS_DIR)[0]


def _detail(
    style_id: str, files: StyleFiles, modified_at: datetime, screenshots: list[str] | None = None
) -> StyleDetail:
    meta = parse_frontmatter(files.get(ENTRY_NAME, "")) or {}
    return StyleDetail(
        id=style_id,
        name=meta.get("name", "").strip() or style_id,
        category=meta.get("category", "").strip() or UNCATEGORIZED,
        description=meta.get("description", "").strip() or None,
        files=files,
        modified_at=modified_at,
        screenshots=screenshots or [],
    )


def _name_of(files: StyleFiles) -> str:
    return (parse_frontmatter(files.get(ENTRY_NAME, "")) or {}).get("name", "").strip()


# ---- 正式版本 -----------------------------------------------------------


def _saved_summaries(data_dir: Path | str) -> list[StyleSummary]:
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
        summaries.append(
            _summary(
                child.name,
                files,
                _mtime(child),
                draft_dir(data_dir, child.name),
                _screenshots_of(child),
            )
        )
    return summaries


def _summary(
    style_id: str,
    files: StyleFiles,
    modified_at: datetime,
    draft: Path,
    screenshots: list[str],
) -> StyleSummary:
    detail = _detail(style_id, files, modified_at)
    return StyleSummary(
        id=detail.id,
        name=detail.name,
        category=detail.category,
        description=detail.description,
        reference_count=sum(1 for p in files if p.startswith("references/")),
        exemplar_count=sum(1 for p in files if p.startswith("exemplars/")),
        modified_at=detail.modified_at,
        has_draft=draft.is_dir(),
        cover=screenshots[0] if screenshots else None,
    )


def _new_draft_summaries(data_dir: Path | str) -> list[StyleSummary]:
    """只有草稿、从未保存过的风格。草稿里的 STYLE.md 可能已经不合法（被改坏或删了 frontmatter），
    照样列出来，让用户能回去继续改或者放弃。"""
    root = drafts_root(data_dir)
    if not root.is_dir():
        return []
    summaries: list[StyleSummary] = []
    for child in sorted(root.iterdir()):
        if not is_valid_style_id(child.name) or child.is_symlink() or not child.is_dir():
            continue
        if style_dir(data_dir, child.name).exists():
            continue
        files, _problems = _read_tree(child)
        base = _summary(child.name, files, _mtime(child), child, _screenshots_of(child))
        name = base.name if base.name != child.name else "未命名风格"
        summaries.append(replace(base, name=name, is_new=True))
    return summaries


def list_saved_styles(data_dir: Path | str) -> list[StyleSummary]:
    """只含有正式版本的风格（不含从未保存过的草稿），按分类、名称排序。导入脚本、创建项目等
    只认已保存风格的调用方用这个，不要用 `list_styles`。"""
    return sorted(_saved_summaries(data_dir), key=lambda s: (s.category, s.name))


def list_styles(data_dir: Path | str) -> list[StyleSummary]:
    """正式版本加上从未保存过的草稿（`is_new`），按分类、名称排序；坏的正式版本目录跳过并记警告。"""
    summaries = [*_saved_summaries(data_dir), *_new_draft_summaries(data_dir)]
    return sorted(summaries, key=lambda s: (s.category, s.name))


def get_style(data_dir: Path | str, style_id: str) -> StyleDetail:
    path = _saved_path(data_dir, style_id)
    if not path.is_dir():
        raise StyleNotFoundError(style_id)
    files, _problems = _read_tree(path)
    if ENTRY_NAME not in files:
        raise StyleNotFoundError(style_id)
    return _detail(style_id, files, _mtime(path), _screenshots_of(path))


def read_style_files(data_dir: Path | str, style_id: str) -> StyleFiles:
    """正式版本的全部文件（创建项目时复制进 `style/` 用）。"""
    return get_style(data_dir, style_id).files


def style_exists(data_dir: Path | str, style_id: str) -> bool:
    return is_valid_style_id(style_id) and style_dir(data_dir, style_id).is_dir()


def draft_dir_exists(data_dir: Path | str, style_id: str) -> bool:
    return is_valid_style_id(style_id) and draft_dir(data_dir, style_id).is_dir()


def style_is_usable(data_dir: Path | str, style_id: str) -> bool:
    """正式版本存在且读得出来（有 `STYLE.md`）。目录被手工弄坏时 `style_exists` 仍为真，
    创建项目、设默认风格要用这个。"""
    try:
        get_style(data_dir, style_id)
    except StyleNotFoundError:
        return False
    return True


def style_known(data_dir: Path | str, style_id: str) -> bool:
    """有正式版本或草稿（从未保存的新风格只有草稿）。"""
    return is_valid_style_id(style_id) and (
        style_dir(data_dir, style_id).is_dir() or draft_dir(data_dir, style_id).is_dir()
    )


def _ensure_unique_name(data_dir: Path | str, name: str, *, except_id: str | None) -> None:
    for existing in _saved_summaries(data_dir):
        if existing.id != except_id and existing.name.strip() == name:
            raise DuplicateStyleNameError(f"已有同名的风格：{name}")


def import_style(
    data_dir: Path | str,
    files: StyleFiles,
    *,
    style_id: str | None = None,
    overwrite: bool = False,
    screenshots_from: Path | None = None,
) -> StyleDetail:
    """校验后直接写成正式版本（迁移旧表、导入脚本用）。`style_id` 为空时生成新 id；
    目录已存在且没有 `overwrite` 时抛 `StyleExistsError`；名称与别的风格重复抛
    `DuplicateStyleNameError`；内容不合法抛 `StyleValidationError`，什么都不写。
    `screenshots_from` 是另一个风格目录时，把它的截图一起复制过来。"""
    errors = validate_style_files(files)
    if errors:
        raise StyleValidationError(errors)
    new_id = style_id if style_id is not None else uuid4().hex
    if not is_valid_style_id(new_id):
        raise StyleValidationError([f"风格 id 不合法：{new_id!r}"])
    if style_dir(data_dir, new_id).exists() and not overwrite:
        raise StyleExistsError(new_id)
    _ensure_unique_name(data_dir, _name_of(files), except_id=new_id)
    _install(files, style_dir(data_dir, new_id), screenshots_from=screenshots_from)
    return get_style(data_dir, new_id)


def duplicate_style(data_dir: Path | str, style_id: str) -> StyleDetail:
    """复制成独立的一份，名称是「原名（副本）」，已占用时依次「（副本 2）」「（副本 3）」…"""
    source = get_style(data_dir, style_id)
    taken = {s.name.strip() for s in _saved_summaries(data_dir)}
    candidate, n = f"{source.name}（副本）", 1
    while candidate in taken:
        n += 1
        candidate = f"{source.name}（副本 {n}）"
    files = dict(source.files)
    files[ENTRY_NAME] = set_frontmatter_fields(files[ENTRY_NAME], {"name": candidate})
    return import_style(data_dir, files, screenshots_from=style_dir(data_dir, style_id))


def delete_style(data_dir: Path | str, style_id: str) -> None:
    """删除正式版本和草稿；两者都不存在时抛 `StyleNotFoundError`。"""
    saved, draft = _saved_path(data_dir, style_id), _draft_path(data_dir, style_id)
    if not saved.exists() and not draft.exists():
        raise StyleNotFoundError(style_id)
    shutil.rmtree(saved, ignore_errors=True)
    shutil.rmtree(draft, ignore_errors=True)


# ---- 草稿 ---------------------------------------------------------------


def create_new_draft(data_dir: Path | str) -> str:
    """新建风格：生成带模板的草稿，返回新 id；保存之前在列表里标记为 `is_new`。"""
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
        _install(files, draft, screenshots_from=saved)
    return draft_status(data_dir, style_id)


def draft_status(data_dir: Path | str, style_id: str) -> DraftStatus:
    draft = _draft_path(data_dir, style_id)
    if not draft.is_dir():
        raise StyleNotFoundError(style_id)
    files, problems = _read_tree(draft)
    saved = _saved_path(data_dir, style_id)
    is_new = not saved.is_dir()
    screenshots = _screenshots_of(draft)
    dirty = (
        True
        if is_new or problems
        else _read_tree(saved)[0] != files or _screenshots_of(saved) != screenshots
    )
    return DraftStatus(
        id=style_id, is_new=is_new, dirty=dirty, files=sorted(files), screenshots=screenshots
    )


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


def _draft_screenshots_dir(data_dir: Path | str, style_id: str) -> Path:
    """草稿的 `screenshots/` 路径（不保证存在）；是符号链接或普通文件时拒绝，防止写到草稿以外。"""
    draft = _draft_path(data_dir, style_id)
    if not draft.is_dir():
        raise StyleNotFoundError(style_id)
    target = draft / SCREENSHOTS_DIR
    if target.is_symlink():
        raise StylePathError(f"不允许符号链接：{SCREENSHOTS_DIR}")
    if target.exists() and not target.is_dir():
        raise StylePathError(f"{SCREENSHOTS_DIR} 不是目录")
    return target


def _apply_order(directory: Path, ordered: list[str]) -> None:
    """按 `ordered` 的顺序给截图重新编号。两阶段改名（先改临时名再改最终名），中途不会撞名；
    任何一步失败都把已经改过的逆序改回去，目录回到调用前的样子。"""
    pairs = [(old, new) for old, new in renumbered(ordered) if old != new]
    staged = [
        (directory / old, directory / f".mv-{uuid4().hex}", directory / new) for old, new in pairs
    ]
    moved_out: list[tuple[Path, Path]] = []  # 第一阶段已经完成的（临时名，原名）
    moved_in: list[tuple[Path, Path]] = []  # 第二阶段已经完成的（最终名，临时名）
    try:
        for original, temp, _final in staged:
            original.rename(temp)
            moved_out.append((temp, original))
        for _original, temp, final in staged:
            temp.rename(final)
            moved_in.append((final, temp))
    except BaseException:
        for current, previous in [*reversed(moved_in), *reversed(moved_out)]:
            try:
                current.rename(previous)
            except OSError:
                logger.exception("回滚截图改名失败：%s -> %s", current, previous)
        raise


def add_draft_screenshot(data_dir: Path | str, style_id: str, data: bytes) -> str:
    """把一张（调用方已经规范化成 WebP 的）截图追加到草稿末尾，返回文件名；满了抛
    `StyleValidationError`。序号取现有最大序号 + 1，写完后整体重新编号成 001…N（草稿里的编号
    可能被手工或 agent 弄得不连续）。写入失败不留临时文件。"""
    directory = _draft_screenshots_dir(data_dir, style_id)
    names = list_screenshots(directory)[0]
    if len(names) >= MAX_SCREENSHOTS:
        raise StyleValidationError([f"截图最多 {MAX_SCREENSHOTS} 张，请先删除一些"])
    top = max((int(name[:3]) for name in names), default=0)
    name = f"{top + 1:03d}-{hashlib.sha256(data).hexdigest()[:12]}.webp"
    directory.mkdir(exist_ok=True)
    staged = directory / f".shot-{uuid4().hex}.tmp"
    try:
        staged.write_bytes(data)
        staged.replace(directory / name)
    finally:
        staged.unlink(missing_ok=True)
    ordered = list_screenshots(directory)[0]
    _apply_order(directory, ordered)
    return renumbered(ordered)[-1][1]


def screenshot_path(data_dir: Path | str, style_id: str, name: str, *, draft: bool) -> Path:
    """一张截图的文件路径（读取接口用）：名字必须符合规则，目录和文件都不能是符号链接。"""
    if not is_screenshot_name(name):
        raise StylePathError(f"截图文件名不合法：{name!r}")
    base = _draft_path(data_dir, style_id) if draft else _saved_path(data_dir, style_id)
    if not base.is_dir():
        raise StyleNotFoundError(style_id)
    directory, target = base / SCREENSHOTS_DIR, base / SCREENSHOTS_DIR / name
    if directory.is_symlink() or target.is_symlink():
        raise StylePathError(f"不允许符号链接：{SCREENSHOTS_DIR}/{name}")
    if not target.is_file():
        raise StyleNotFoundError(name)
    return target


def delete_draft_screenshot(data_dir: Path | str, style_id: str, name: str) -> None:
    """删除一张截图，剩下的重新编号。"""
    directory = _draft_screenshots_dir(data_dir, style_id)
    if not is_screenshot_name(name) or not (directory / name).is_file():
        raise StyleNotFoundError(name)
    (directory / name).unlink()
    _apply_order(directory, list_screenshots(directory)[0])


def reorder_draft_screenshots(data_dir: Path | str, style_id: str, names: list[str]) -> None:
    """按 `names` 重排截图；它必须正好是当前全部文件名的一个排列，否则抛 `StyleValidationError`。"""
    directory = _draft_screenshots_dir(data_dir, style_id)
    current = list_screenshots(directory)[0]
    if len(names) != len(set(names)) or sorted(names) != current:
        raise StyleValidationError(["新的顺序必须正好包含当前的全部截图，每张一次"])
    _apply_order(directory, names)


def discard_draft(data_dir: Path | str, style_id: str) -> None:
    """丢弃草稿；从未保存的新建风格因此整个消失。风格和草稿都不存在时抛 `StyleNotFoundError`。"""
    draft = _draft_path(data_dir, style_id)
    if draft.is_dir():
        shutil.rmtree(draft)
    elif not _saved_path(data_dir, style_id).is_dir():
        raise StyleNotFoundError(style_id)


def validate_tree(root: Path) -> list[str]:
    """一个风格目录当前的全部问题（读取时发现的 + 内容校验），空列表表示可以保存。
    目录不存在抛 `StyleNotFoundError`。名称是否与别的风格重复不在这里检查（保存时才查）。"""
    if not root.is_dir():
        raise StyleNotFoundError(str(root))
    files, problems = _read_tree(root)
    return [*problems, *validate_style_files(files)]


def validate_draft(data_dir: Path | str, style_id: str) -> list[str]:
    """草稿当前的全部问题，空列表表示可以保存。"""
    return validate_tree(_draft_path(data_dir, style_id))


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def prune_draft(data_dir: Path | str, style_id: str) -> list[str]:
    """删掉草稿里用户界面和草稿接口够不着的东西，返回删掉的相对路径。

    agent 用 Bash 可能留下符号链接、顶层多余的文件或目录、`references/`/`exemplars/` 下的子目录和
    文件名不合法的文件：保存只会 422，界面又删不掉它们，所以每轮结束后清掉。其余内容（包括
    内容不合法的合法路径文件）原样保留，由用户或下一轮对话修。"""
    draft = _draft_path(data_dir, style_id)
    if not draft.is_dir():
        raise StyleNotFoundError(style_id)
    removed: list[str] = []
    for entry in sorted(draft.iterdir()):
        if entry.name in _IGNORED_FILES:
            continue
        if entry.name == ENTRY_NAME and entry.is_file() and not entry.is_symlink():
            continue
        if entry.name == UPLOADS_DIR and entry.is_dir() and not entry.is_symlink():
            continue  # 用户上传的对话附件，随草稿一起删（设计 2026-10-09 修订 R1）
        if entry.name == SCREENSHOTS_DIR and entry.is_dir() and not entry.is_symlink():
            for child in sorted(entry.iterdir()):
                if child.name in _IGNORED_FILES:
                    continue
                if (
                    child.is_symlink()
                    or not child.is_file()
                    or not is_screenshot_name(child.name)
                    or verify_screenshot(child) is not None
                ):
                    _remove(child)
                    removed.append(f"{entry.name}/{child.name}")
            continue
        if (
            entry.name in (REFERENCES_DIR, EXEMPLARS_DIR)
            and entry.is_dir()
            and not entry.is_symlink()
        ):
            for child in sorted(entry.iterdir()):
                if child.name in _IGNORED_FILES:
                    continue
                if child.is_symlink() or not child.is_file() or not is_plain_file_name(child.name):
                    _remove(child)
                    removed.append(f"{entry.name}/{child.name}")
            continue
        _remove(entry)
        if entry.name not in _RUNTIME_DIRS:
            removed.append(entry.name)
    return removed


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
    _install(files, style_dir(data_dir, style_id), screenshots_from=draft)
    shutil.rmtree(draft, ignore_errors=True)
    return get_style(data_dir, style_id)


_SWAP_LEFTOVER = re.compile(r"^\.(?P<id>.+)\.(?P<kind>old|tmp)-[0-9a-f]+$")


def recover_interrupted_swaps(data_dir: Path | str) -> list[str]:
    """启动时收拾 `_swap`/`_install` 被打断留下的 `.<id>.old-*`、`.<id>.tmp-*`（TD-58）。

    两次 rename 之间进程被杀时，正式（或草稿）目录已经改名成 `.old-*` 而新目录还没就位：
    目录缺失就把旧版本改回去；目录在就丢掉这份多余的旧备份。`.tmp-*` 是没装上的半成品，直接删。
    返回被还原的风格 id；某个目录收拾失败只记日志、继续处理其余的。"""
    restored: list[str] = []
    for root in (styles_root(data_dir), drafts_root(data_dir)):
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            found = _SWAP_LEFTOVER.match(entry.name)
            if found is None or entry.is_symlink() or not entry.is_dir():
                continue
            target = root / found["id"]
            try:
                if found["kind"] == "old" and not target.exists():
                    entry.rename(target)
                    restored.append(found["id"])
                else:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                # One bad directory must not keep the app from starting (called from the lifespan).
                logger.exception("风格目录 %s 的残留收拾失败，跳过", entry)
    return restored


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
    "add_draft_screenshot",
    "create_new_draft",
    "delete_draft_screenshot",
    "delete_draft_file",
    "delete_style",
    "discard_draft",
    "draft_dir_exists",
    "draft_status",
    "duplicate_style",
    "get_style",
    "import_style",
    "list_saved_styles",
    "list_styles",
    "open_draft",
    "read_draft_file",
    "prune_draft",
    "read_style_files",
    "recover_interrupted_swaps",
    "reorder_draft_screenshots",
    "save_draft",
    "screenshot_path",
    "style_exists",
    "style_is_usable",
    "style_known",
    "validate_draft",
    "validate_tree",
    "write_draft_file",
]
