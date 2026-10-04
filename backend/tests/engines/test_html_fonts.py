"""HTML 引擎随包字体与覆盖表（子项目 2 设计 §5.3）。"""

from __future__ import annotations

from pathlib import Path

import pytest

import studio.engines.render.html as html_engine

FONTS = Path(html_engine.__file__).parent / "fonts"
_FILES = [
    "anton.woff2",
    "spacemono.woff2",
    "spacemono-bold.woff2",
    "notosanssc-400.woff2",
    "notosanssc-700.woff2",
]
_NOTO_BUDGET = 3 * 1024 * 1024


@pytest.mark.parametrize("name", _FILES)
def test_font_file_is_woff2(name: str) -> None:
    assert (FONTS / name).read_bytes()[:4] == b"wOF2"


@pytest.mark.parametrize("name", ["notosanssc-400.woff2", "notosanssc-700.woff2"])
def test_noto_subset_within_budget(name: str) -> None:
    assert (FONTS / name).stat().st_size < _NOTO_BUDGET


def test_coverage_contains_common_characters() -> None:
    covered = set((FONTS / "coverage.txt").read_text(encoding="utf-8"))
    needed = (
        set("天空为什么是蓝的瑞利散射")
        | set("，。！？：；、（）《》——…")
        | {chr(c) for c in range(0x20, 0x7F)}
    )
    assert needed <= covered


@pytest.mark.parametrize("name", ["OFL-NotoSansSC.txt", "OFL-Anton.txt", "OFL-SpaceMono.txt"])
def test_license_files_present(name: str) -> None:
    assert "SIL OPEN FONT LICENSE" in (FONTS / name).read_text(encoding="utf-8").upper()
