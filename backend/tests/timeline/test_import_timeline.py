"""`studio.timeline.imported`：歌曲分析的网格换算与 MV 时间轴哈希（produce 设计 §6）。"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from studio.timeline.build import TimelineError
from studio.timeline.imported import downbeat_times, effective_grid, import_hash

BPM = 120.0  # beat 0.5 s, bar 2.0 s

ANALYSIS: dict[str, Any] = {
    "source_hash": "a" * 64,
    "duration": 30.0,
    "bpm": BPM,
    "offset": 0.5,
    "residual_ms": 4.0,
    "confidence": 0.9,
    "hop": 0.5,
    "energy": [0.5] * 60,
}


def _analysis(**overrides: Any) -> dict[str, Any]:
    doc = copy.deepcopy(ANALYSIS)
    doc.update(overrides)
    return doc


def test_effective_grid_is_the_analysis_value() -> None:
    assert effective_grid(ANALYSIS) == (BPM, 0.5)
    assert effective_grid(_analysis(bpm=100, offset=1.25)) == (100.0, 1.25)


@pytest.mark.parametrize(
    "analysis",
    [
        _analysis(bpm="fast"),
        _analysis(bpm=None),
        _analysis(bpm=True),
        _analysis(bpm=300),
        _analysis(offset=float("nan")),
        _analysis(offset="0"),
        {},
    ],
)
def test_effective_grid_rejects_malformed_values(analysis: dict[str, Any]) -> None:
    with pytest.raises(TimelineError):
        effective_grid(analysis)


def test_effective_grid_rejects_a_document_that_is_not_an_object() -> None:
    not_a_dict: Any = []
    with pytest.raises(TimelineError):
        effective_grid(not_a_dict)


def test_downbeat_times_cover_the_song() -> None:
    assert downbeat_times(BPM, 0.5, 6.5) == pytest.approx([0.5, 2.5, 4.5, 6.5])
    # an offset beyond the first bar extends the grid backwards to t >= 0
    assert downbeat_times(BPM, 3.0, 6.0) == pytest.approx([1.0, 3.0, 5.0])


@pytest.mark.parametrize(
    ("bpm", "offset", "duration"),
    [(0, 0, 10), (-120, 0, 10), (float("nan"), 0, 10), (120, float("inf"), 10), ("x", 0, 10)],
)
def test_downbeat_times_rejects_malformed_input(bpm: Any, offset: Any, duration: Any) -> None:
    with pytest.raises(TimelineError):
        downbeat_times(bpm, offset, duration)


def test_import_hash_follows_the_timeline_the_source_and_the_range() -> None:
    base = import_hash("t" * 64, "s" * 64, (1.0, 5.0))
    assert base == import_hash("t" * 64, "s" * 64, (1.0, 5.0))
    assert base != import_hash("u" * 64, "s" * 64, (1.0, 5.0))
    assert base != import_hash("t" * 64, "z" * 64, (1.0, 5.0))
    assert base != import_hash("t" * 64, "s" * 64, (1.0, 6.0))
