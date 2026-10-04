"""`studio.timeline.notation.parse_at`：“小节.拍”记法换算（设计 §4.3）。"""

from __future__ import annotations

import pytest

from studio.timeline.notation import parse_at


def test_first_beat_of_first_bar_is_zero() -> None:
    assert parse_at("1.1", bpm=120) == 0.0


def test_second_bar_first_beat_at_120_bpm() -> None:
    # 120 BPM: one beat = 0.5s, one 4/4 bar = 2s.
    assert parse_at("2.1", bpm=120) == pytest.approx(2.0)


def test_beat_within_bar() -> None:
    assert parse_at("3.2", bpm=120) == pytest.approx(4.5)


def test_fraction_of_a_whole_note_is_added() -> None:
    # 1/16 of a whole note = a quarter of a beat = 0.125s at 120 BPM.
    assert parse_at("4.1+1/16", bpm=120) == pytest.approx(6.0 + 0.125)


def test_custom_beats_per_bar() -> None:
    assert parse_at("2.1", bpm=60, beats_per_bar=3) == pytest.approx(3.0)


_BAD = ["", "3", "0.1", "1.0", "a.b", "1.1+", "1.1+1/0", "1.1+x/4", "-1.1"]


@pytest.mark.parametrize("text", _BAD)
def test_invalid_notation_raises(text: str) -> None:
    with pytest.raises(ValueError):
        parse_at(text, bpm=120)


def test_non_positive_bpm_raises() -> None:
    with pytest.raises(ValueError):
        parse_at("1.1", bpm=0)
