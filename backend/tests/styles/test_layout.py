"""风格目录布局：路径与 id 校验。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from studio.styles.layout import (
    draft_dir,
    drafts_root,
    is_valid_style_id,
    style_dir,
    styles_root,
)


def test_directories_live_under_the_data_dir() -> None:
    data = Path("/data")
    assert styles_root(data) == data / "styles"
    assert drafts_root(data) == data / "style-drafts"
    assert style_dir(data, "abc123") == data / "styles" / "abc123"
    assert draft_dir(data, "abc123") == data / "style-drafts" / "abc123"


@pytest.mark.parametrize("style_id", ["abc123", "0f" * 16, "A1b2"])
def test_plain_ids_are_valid(style_id: str) -> None:
    assert is_valid_style_id(style_id)


@pytest.mark.parametrize(
    "style_id", ["", ".", "..", "a/b", "../x", "a b", ".hidden", "x" * 65, "a\\b"]
)
def test_ids_that_could_escape_the_directory_are_invalid(style_id: str) -> None:
    assert not is_valid_style_id(style_id)


@pytest.mark.parametrize("fn", [style_dir, draft_dir])
def test_invalid_ids_are_rejected_when_building_paths(fn: Callable[[Path, str], Path]) -> None:
    with pytest.raises(ValueError):
        fn(Path("/data"), "../evil")
