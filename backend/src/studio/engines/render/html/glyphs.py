"""内置字体的字符覆盖表（`fonts/coverage.txt`，由 `scripts/build_fonts.sh` 生成）。"""

from __future__ import annotations

from functools import cache
from pathlib import Path

_COVERAGE = Path(__file__).parent / "fonts" / "coverage.txt"


@cache
def covered_characters() -> frozenset[str]:
    return frozenset(_COVERAGE.read_text(encoding="utf-8"))


def missing_characters(text: str) -> list[str]:
    """`text` 中不在内置字体里的字符（去重，保持首次出现的顺序，忽略空白）。"""
    covered = covered_characters()
    return [ch for ch in dict.fromkeys(text) if not ch.isspace() and ch not in covered]
