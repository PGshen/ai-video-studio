"""“小节.拍”记法换算（设计 §4.3）。

`3.2` 是第 3 小节第 2 拍（都从 1 开始）；`4.1+1/16` 在此基础上加 1/16 全音符。
拍按四分音符计，一个全音符等于 4 拍，与每小节几拍无关。
"""

from __future__ import annotations

import re

_PATTERN = re.compile(r"^(\d+)\.(\d+)(?:\+(\d+)/(\d+))?$")
_BEATS_PER_WHOLE_NOTE = 4


def parse_at(text: str, bpm: float, beats_per_bar: int = 4) -> float:
    if bpm <= 0:
        raise ValueError(f"BPM 必须为正数：{bpm}")
    match = _PATTERN.match(text.strip())
    if match is None:
        raise ValueError(f"无法解析的小节.拍记法：{text!r}（示例：3.2、4.1+1/16）")
    bar, beat = int(match.group(1)), int(match.group(2))
    if bar < 1 or beat < 1:
        raise ValueError(f"小节和拍都从 1 开始：{text!r}")
    extra_beats = 0.0
    if match.group(3) is not None:
        denominator = int(match.group(4))
        if denominator == 0:
            raise ValueError(f"分数的分母不能为 0：{text!r}")
        extra_beats = int(match.group(3)) / denominator * _BEATS_PER_WHOLE_NOTE
    beat_seconds = 60.0 / bpm
    return ((bar - 1) * beats_per_bar + (beat - 1) + extra_beats) * beat_seconds
