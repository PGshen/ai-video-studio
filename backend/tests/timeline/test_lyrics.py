"""LRC parsing (mv-lyrics design §3.1): rules, ends, and the validation that rejects bad input."""

from __future__ import annotations

import pytest

from studio.timeline.lyrics import MAX_LRC_BYTES, LyricsError, parse_lrc
from studio.timeline.schema import LyricLine

DURATION = 100.0


def lines(text: str, duration: float = DURATION) -> list[tuple[str, float, float]]:
    return [(item.text, item.start, item.end) for item in parse_lrc(text, duration)]


def test_basic_lines_end_where_the_next_one_starts() -> None:
    result = lines("[00:01.00]第一句\n[00:04.50]第二句\n[00:08.00]第三句\n")
    assert result == [("第一句", 1.0, 4.5), ("第二句", 4.5, 8.0), ("第三句", 8.0, 13.0)]


def test_the_last_line_ends_five_seconds_later_or_at_the_song_end() -> None:
    assert lines("[00:10.00]last", 100.0) == [("last", 10.0, 15.0)]
    assert lines("[00:10.00]last", 12.0) == [("last", 10.0, 12.0)]


def test_returns_lyric_line_models() -> None:
    assert isinstance(parse_lrc("[00:01.00]a", DURATION)[0], LyricLine)


@pytest.mark.parametrize(
    ("stamp", "seconds"),
    [
        ("[00:01]", 1.0),
        ("[00:01.5]", 1.5),
        ("[00:01.50]", 1.5),
        ("[00:01.123]", 1.123),
        ("[00:01.1234]", 1.1234),
        ("[00:01.123456]", 1.123456),
        ("[01:02.00]", 62.0),
    ],
)
def test_timestamp_precision_variants(stamp: str, seconds: float) -> None:
    assert lines(f"{stamp}x") == [("x", pytest.approx(seconds), pytest.approx(seconds + 5))]


def test_several_timestamps_on_one_line_make_several_lines_in_time_order() -> None:
    result = lines("[00:20.00][00:05.00]副歌\n[00:10.00]中间")
    assert [(t, s) for t, s, _ in result] == [("副歌", 5.0), ("中间", 10.0), ("副歌", 20.0)]
    assert result[0][2] == 10.0


def test_a_positive_offset_moves_lyrics_earlier_and_a_negative_one_later() -> None:
    assert lines("[offset:500]\n[00:05.00]a")[0][1] == 4.5
    assert lines("[offset:-500]\n[00:05.00]a")[0][1] == 5.5


def test_an_offset_that_pushes_a_line_before_zero_clamps_to_zero() -> None:
    assert lines("[offset:1000]\n[00:00.20]a")[0][1] == 0.0


def test_metadata_tags_are_ignored() -> None:
    text = "[ti:歌名]\n[ar:歌手]\n[al:专辑]\n[by:某人]\n[length:03:20]\n[00:01.00]词"
    assert lines(text) == [("词", 1.0, 6.0)]


def test_word_level_tags_are_stripped_and_text_kept() -> None:
    assert lines("[00:01.00]<00:01.00>你<00:01.40>好")[0][0] == "你好"


def test_an_empty_text_line_is_an_end_marker_not_a_lyric() -> None:
    result = lines("[00:01.00]一\n[00:03.00]\n[00:08.00]二")
    assert result == [("一", 1.0, 3.0), ("二", 8.0, 13.0)]


def test_lines_at_the_same_moment_keep_file_order_and_share_the_next_end() -> None:
    result = lines("[00:02.00]中文\n[00:02.00]English\n[00:06.00]下一句")
    assert result == [("中文", 2.0, 6.0), ("English", 2.0, 6.0), ("下一句", 6.0, 11.0)]


def test_out_of_order_lines_are_sorted_by_time() -> None:
    assert [t for t, _, _ in lines("[00:09.00]b\n[00:01.00]a")] == ["a", "b"]


def test_text_with_colons_and_brackets_is_kept_after_the_timestamps() -> None:
    assert lines("[00:01.00][副歌] 他说:你好[大声]")[0][0] == "[副歌] 他说:你好[大声]"


def test_bom_crlf_and_bytes_input() -> None:
    raw = "﻿[00:01.00]一\r\n[00:03.00]二\r\n".encode()
    assert [t for t, _, _ in [(i.text, i.start, i.end) for i in parse_lrc(raw, DURATION)]] == [
        "一",
        "二",
    ]


def test_surrounding_whitespace_is_trimmed_including_full_width_spaces() -> None:
    assert lines("[00:01.00]　 你好 　")[0][0] == "你好"


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("就是一些没有时间戳的歌词\n第二行", "时间戳"),
        ("", "时间戳"),
        ("[ti:只有元信息]\n[ar:x]", "时间戳"),
        ("[00:01.00]\n[00:05.00]", "至少"),
        ("[05:00.00]b", "至少"),
    ],
)
def test_invalid_input_is_rejected_with_a_reason(text: str, needle: str) -> None:
    with pytest.raises(LyricsError) as caught:
        parse_lrc(text, DURATION)
    assert needle in str(caught.value)


def test_invalid_utf8_is_rejected() -> None:
    with pytest.raises(LyricsError, match="UTF-8"):
        parse_lrc(b"\xff\xfe\x00bad", DURATION)


def test_oversized_input_is_rejected() -> None:
    big = "[00:01.00]" + "词" * MAX_LRC_BYTES
    with pytest.raises(LyricsError, match="200 KB"):
        parse_lrc(big, DURATION)


def test_a_line_starting_within_a_second_past_the_end_is_dropped() -> None:
    assert lines("[01:30.00]正文\n[01:40.50]尾声", 100.0) == [("正文", 90.0, 100.0)]


def test_a_line_far_past_the_end_is_dropped_without_rejecting_the_file() -> None:
    # TD-84: one stray late entry (even an empty end marker) must not cost the whole upload.
    assert lines("[00:01.00]a\n[05:00.00]b\n[06:00.00]\n[00:10.00]c") == [
        ("a", 1.0, 10.0),
        ("c", 10.0, 15.0),
    ]


def test_parsing_is_linear_even_with_tens_of_thousands_of_lines() -> None:
    import time

    text = "[0:00]a\n" * 24000  # ~190 KB, all at the same moment
    started = time.perf_counter()
    result = parse_lrc(text, DURATION)
    assert len(result) == 24000
    assert time.perf_counter() - started < 1.0
    spread = "\n".join(f"[{i // 60}:{i % 60:02d}.00]x" for i in range(0, 90)) * 1
    assert len(parse_lrc(spread, DURATION)) == 90
