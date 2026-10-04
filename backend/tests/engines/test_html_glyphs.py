"""`engines.render.html.glyphs`：内置字体覆盖表。"""

from __future__ import annotations

from studio.engines.render.html.glyphs import covered_characters, missing_characters


def test_common_text_is_covered() -> None:
    assert missing_characters("天空为什么是蓝的，ABC 123！") == []


def test_rare_characters_are_reported_once_in_order() -> None:
    assert missing_characters("龘a𠮷龘") == ["龘", "𠮷"]


def test_whitespace_is_ignored_and_table_is_cached() -> None:
    assert missing_characters(" \n\t") == []
    assert covered_characters() is covered_characters()
