"""对齐用的文本归一化（计划 M3 T2）。

迁移自 `../ai-video/backend/app/services/narrative_validator.py` 里的
`normalize_alignment_text` 及其标点映射表——只搬这一个函数，不搬整个旧
validator；`stages.narrative.schema`（T3）依赖 `engines` 是允许的方向
（ARCHITECTURE §2 依赖表：stages 可以依赖 engines）。
"""

from __future__ import annotations

import unicodedata

_WHITESPACE = {" ", "\t", "\r", "\n", "　"}
_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)


def normalize_alignment_text(text: str) -> str:
    """标点归一化为半角、去空白，供 cue_text/narration 比较和字符级对齐用。"""
    normalized = unicodedata.normalize("NFKC", text).translate(_PUNCTUATION_TRANSLATION)
    return "".join(char for char in normalized if char not in _WHITESPACE)
