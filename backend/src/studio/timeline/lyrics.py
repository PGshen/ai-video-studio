"""LRC lyrics → `LyricLine`s (mv-lyrics design §3.1). Pure: no files, no project knowledge.

Only timestamped LRC is accepted. Lines are used whole (no word-level timing): a line ends where
the next line (or an empty-text end marker) starts.
"""

from __future__ import annotations

import re

from studio.timeline.schema import LyricLine

LYRICS_PATH = "music/lyrics.lrc"
"""Where the upload endpoint stores the lyrics (tool-managed, relative to the workspace)."""
MAX_LRC_BYTES = 200_000
LAST_LINE_SECONDS = 5.0
_PAST_END_TOLERANCE = 1.0

_STAMP = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,6}))?\]")
_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]\s*$", re.IGNORECASE)
_WORD_TAG = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,6})?>")
_MAX_SHOWN = 5


class LyricsError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = tuple(errors)
        super().__init__("歌词不可用：" + "；".join(self.errors[:_MAX_SHOWN]))


def _decode(data: bytes | str) -> str:
    if isinstance(data, str):
        text = data
        size = len(text.encode("utf-8"))
    else:
        size = len(data)
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise LyricsError(["文件不是 UTF-8 编码"]) from exc
    if size > MAX_LRC_BYTES:
        raise LyricsError([f"文件超过 {MAX_LRC_BYTES // 1000} KB"])
    return text.removeprefix("﻿")


def _seconds(minutes: str, seconds: str, fraction: str | None) -> float:
    return int(minutes) * 60 + int(seconds) + (float(f"0.{fraction}") if fraction else 0.0)


def parse_lrc(data: bytes | str, duration: float) -> list[LyricLine]:
    """Parse LRC text (or UTF-8 bytes) for a song `duration` seconds long."""
    text = _decode(data)
    offset = 0.0
    entries: list[tuple[float, str]] = []  # (start, text); empty text is an end marker
    saw_stamp = False
    for raw in text.splitlines():
        line = raw.strip()
        found = _OFFSET.match(line)
        if found:
            offset = int(found.group(1)) / 1000.0
            continue
        stamps: list[float] = []
        position = 0
        while True:
            match = _STAMP.match(line, position)
            if match is None:
                break
            stamps.append(_seconds(*match.groups()))
            position = match.end()
        if not stamps:
            continue
        saw_stamp = True
        body = _WORD_TAG.sub("", line[position:]).strip()
        entries.extend((stamp, body) for stamp in stamps)
    if not saw_stamp:
        raise LyricsError(["没有找到时间戳：只支持带时间戳的 LRC（形如 [00:12.34]歌词）"])

    adjusted: list[tuple[float, str]] = []
    for start, body in entries:
        start = max(0.0, start - offset)
        if start > duration + _PAST_END_TOLERANCE:
            continue  # a stray entry past the end costs only itself, not the whole file
        adjusted.append((start, body))
    adjusted.sort(key=lambda item: item[0])  # stable: same moment keeps file order

    # `following[i]`: the next strictly later moment after entry i (one backward pass, linear).
    following: list[float | None] = [None] * len(adjusted)
    for index in range(len(adjusted) - 2, -1, -1):
        nxt = adjusted[index + 1][0]
        following[index] = nxt if nxt > adjusted[index][0] else following[index + 1]

    result: list[LyricLine] = []
    for index, (start, body) in enumerate(adjusted):
        if not body or start >= duration:
            continue
        end = following[index]
        if end is None:
            end = min(start + LAST_LINE_SECONDS, duration)
        result.append(LyricLine(text=body, start=round(start, 6), end=round(min(end, duration), 6)))
    if not result:
        raise LyricsError(["至少要有一句歌词（只有结束标记或元信息，或者时间都晚于歌曲时长）"])
    return result


def clip_to_range(lines: list[LyricLine], start: float, end: float) -> list[LyricLine]:
    """Lines inside `[start, end]`, relative to `start`; straddlers are cut, others dropped."""
    result: list[LyricLine] = []
    for line in lines:
        first, last = max(line.start, start), min(line.end, end)
        if last > first:
            result.append(
                LyricLine(text=line.text, start=round(first - start, 6), end=round(last - start, 6))
            )
    return result
