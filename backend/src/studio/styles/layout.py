"""风格目录布局：`<data>/styles/<id>/` 是正式版本，`<data>/style-drafts/<id>/` 是草稿。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

ENTRY_NAME: Final = "STYLE.md"
REFERENCES_DIR: Final = "references"
EXEMPLARS_DIR: Final = "exemplars"
SCREENSHOTS_DIR: Final = "screenshots"
UPLOADS_DIR: Final = "uploads"
"""对话附件目录（设计 2026-10-09 修订 R1），和 `workspace.scope.UPLOADS_DIR` 同名；styles 不能依赖
workspace，所以各写一份，由 `tests/styles/test_layout.py` 保证一致。"""

_STYLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")


def is_valid_style_id(style_id: str) -> bool:
    """id 只允许字母、数字、下划线和连字符（不以符号开头），因此不可能越出风格根目录。"""
    return _STYLE_ID.match(style_id) is not None


def _checked(style_id: str) -> str:
    if not is_valid_style_id(style_id):
        raise ValueError(f"风格 id 不合法：{style_id!r}")
    return style_id


def styles_root(data_dir: Path | str) -> Path:
    return Path(data_dir) / "styles"


def drafts_root(data_dir: Path | str) -> Path:
    return Path(data_dir) / "style-drafts"


def style_dir(data_dir: Path | str, style_id: str) -> Path:
    """正式版本目录（不保证已存在）；`style_id` 不合法时抛 `ValueError`。"""
    return styles_root(data_dir) / _checked(style_id)


def draft_dir(data_dir: Path | str, style_id: str) -> Path:
    """草稿目录（不保证已存在）；`style_id` 不合法时抛 `ValueError`。"""
    return drafts_root(data_dir) / _checked(style_id)
