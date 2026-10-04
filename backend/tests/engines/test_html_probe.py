"""`engines.render.html.probe`：采样、拼图、冒烟、确定性、beat 敏感度（假页面驱动）。"""

from __future__ import annotations

import copy
import hashlib
import io
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from PIL import Image

from studio.engines.render.html.browser import BrowserClosed, RenderTimeout, SceneRenderError
from studio.engines.render.html.probe import (
    FrameMetrics,
    beat_sensitivity,
    boundary_diff,
    contact_sheet,
    determinism_check,
    frame_metrics,
    is_flat,
    sample_times,
    section_info,
    smoke_run,
)

TIMELINE: dict[str, Any] = {
    "duration": 12.0,
    "grid": None,
    "sections": [
        {"id": "s-a", "label": "甲", "start": 0.0, "end": 6.0},
        {"id": "s-b", "label": "乙", "start": 6.0, "end": 12.0},
    ],
    "narration": [
        {
            "scene_id": "s-a",
            "start": 0.0,
            "end": 6.0,
            "beats": [{"start": 0.5, "end": 2.0, "cue_text": "一"}],
        },
        {
            "scene_id": "s-b",
            "start": 6.0,
            "end": 12.0,
            "beats": [
                {"start": 6.5, "end": 8.0, "cue_text": "二"},
                {"start": 8.5, "end": 10.0, "cue_text": "三"},
                {"start": 10.5, "end": 11.8, "cue_text": "四"},
            ],
        },
    ],
    "moments": [],
    "music": None,
    "lyrics": [],
}


def _jpeg(flat: bool) -> bytes:
    image = Image.new("RGB", (64, 36), (20, 20, 20))
    if not flat:
        for x in range(64):
            for y in range(36):
                image.putpixel((x, y), ((x * 4) % 256, (y * 7) % 256, 128))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


class FakePage:
    def __init__(
        self,
        hash_fn: Callable[[float, Mapping[str, Any]], str] | None = None,
        jpeg_fn: Callable[[float], bytes] | None = None,
    ) -> None:
        self.timeline: Mapping[str, Any] = copy.deepcopy(TIMELINE)
        self.errors: list[str] = []
        self.poisoned = False
        self._hash_fn = hash_fn or (lambda t, tl: f"{t}")
        self._jpeg_fn = jpeg_fn or (lambda t: _jpeg(flat=False))
        self.rendered: list[float] = []

    async def render_hash(self, t: float) -> str:
        self.rendered.append(t)
        return self._hash_fn(t, self.timeline)

    async def render_jpeg(self, t: float) -> bytes:
        self.rendered.append(t)
        return self._jpeg_fn(t)

    async def set_timeline(self, timeline: Mapping[str, Any]) -> None:
        self.timeline = timeline

    async def close(self) -> None:
        return None


def _digest(*parts: object) -> str:
    return hashlib.sha1(repr(parts).encode()).hexdigest()


def _beat_starts(timeline: Mapping[str, Any], scene_id: str) -> list[float]:
    entry = next(n for n in timeline["narration"] if n["scene_id"] == scene_id)
    return [b["start"] for b in entry["beats"]]


# ---- sample_times -------------------------------------------------------------------------


def test_sample_times_include_beat_points_and_stay_inside_the_section() -> None:
    beats = TIMELINE["narration"][1]["beats"]
    times = sample_times(6.0, 12.0, beats)
    assert times == sorted(times)
    assert all(6.0 <= t < 12.0 for t in times)
    for expected in (6.05, 11.95, 6.8, 7.9, 8.8, 9.9, 10.8, 11.7):
        assert any(abs(t - expected) < 1e-6 for t in times), expected


def test_sample_times_are_capped_and_deduplicated() -> None:
    beats = [{"start": 1.0 + i * 0.1, "end": 1.05 + i * 0.1, "cue_text": ""} for i in range(30)]
    times = sample_times(0.0, 10.0, beats, cap=16)
    assert len(times) <= 16
    assert len(times) == len(set(times))
    assert times[0] == pytest.approx(0.05)
    assert times[-1] == pytest.approx(9.95)


def test_sample_times_drop_points_outside_a_short_section() -> None:
    times = sample_times(0.0, 0.4, [{"start": 0.0, "end": 0.4, "cue_text": ""}])
    assert times and all(0.0 <= t < 0.4 for t in times)


# ---- images -----------------------------------------------------------------------------


def test_frame_metrics_and_flatness() -> None:
    flat, busy = frame_metrics(_jpeg(flat=True)), frame_metrics(_jpeg(flat=False))
    assert isinstance(flat, FrameMetrics)
    assert is_flat(flat) and not is_flat(busy)
    assert busy.std > flat.std


def test_contact_sheet_layout() -> None:
    frames = [(f"f{i}", _jpeg(flat=False)) for i in range(6)]
    sheet = Image.open(io.BytesIO(contact_sheet(frames, cols=4, thumb=(160, 90))))
    assert sheet.format == "PNG"
    assert sheet.size == (4 * 160, 2 * 90)


def test_contact_sheet_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        contact_sheet([])


async def test_boundary_diff_is_zero_for_identical_frames_and_positive_for_a_cut() -> None:
    same = FakePage(jpeg_fn=lambda t: _jpeg(flat=False))
    assert await boundary_diff(same, 6.0) == pytest.approx(0.0, abs=1e-6)
    cut = FakePage(jpeg_fn=lambda t: _jpeg(flat=t < 6.0))
    assert await boundary_diff(cut, 6.0) > 10


# ---- smoke_run ----------------------------------------------------------------------------


def test_section_info_reads_range_and_beats() -> None:
    start, end, beats = section_info(TIMELINE, "s-b")
    assert (start, end) == (6.0, 12.0)
    assert [b["cue_text"] for b in beats] == ["二", "三", "四"]
    with pytest.raises(KeyError):
        section_info(TIMELINE, "nope")


async def test_smoke_run_reports_exceptions_once_with_scene_label() -> None:
    def jpeg(t: float) -> bytes:
        if t >= 8.0:
            raise SceneRenderError(f"[scene s-b @lt={t - 6:.3f}] boom")
        return _jpeg(flat=False)

    report = await smoke_run(FakePage(jpeg_fn=jpeg), TIMELINE, "s-b")
    assert len(report.errors) == 1
    assert "[scene s-b" in report.errors[0] and "boom" in report.errors[0]


async def test_smoke_run_flags_flat_frames_as_warnings_not_errors() -> None:
    report = await smoke_run(FakePage(jpeg_fn=lambda t: _jpeg(flat=True)), TIMELINE, "s-a")
    assert report.errors == []
    assert report.warnings and "空白" in report.warnings[0]


async def test_smoke_run_collects_console_errors_raised_while_rendering() -> None:
    holder: dict[str, FakePage] = {}

    def jpeg(t: float) -> bytes:
        holder["page"].errors.append("console.error: boom from lib")
        return _jpeg(flat=False)

    page = FakePage(jpeg_fn=jpeg)
    holder["page"] = page
    report = await smoke_run(page, TIMELINE, "s-a")
    assert sum("boom from lib" in e for e in report.errors) == 1


async def test_smoke_run_ignores_errors_recorded_before_it_started() -> None:
    page = FakePage()
    page.errors.append("console.error: earlier problem")
    report = await smoke_run(page, TIMELINE, "s-a")
    assert report.errors == [] and report.warnings == []


async def test_smoke_run_lets_a_closed_browser_propagate() -> None:
    def jpeg(t: float) -> bytes:
        raise BrowserClosed("Target page, context or browser has been closed")

    with pytest.raises(BrowserClosed):
        await smoke_run(FakePage(jpeg_fn=jpeg), TIMELINE, "s-a")


async def test_smoke_run_stops_at_a_timeout() -> None:
    def jpeg(t: float) -> bytes:
        raise RenderTimeout(t, 10.0)

    page = FakePage(jpeg_fn=jpeg)
    report = await smoke_run(page, TIMELINE, "s-a")
    assert any("渲染超时" in e and "s-a" in e for e in report.errors)
    assert len(page.rendered) == 1


# ---- determinism ----------------------------------------------------------------------------


async def test_determinism_check_passes_for_pure_pages() -> None:
    assert await determinism_check(FakePage(), [1.0, 2.0, 3.0]) == []


async def test_determinism_check_reports_order_dependent_frames() -> None:
    state = {"n": 0}

    def hash_fn(t: float, tl: Mapping[str, Any]) -> str:
        state["n"] += 1
        return _digest(t, state["n"])

    assert await determinism_check(FakePage(hash_fn=hash_fn), [1.0, 2.0]) == [1.0, 2.0]


# ---- beat sensitivity --------------------------------------------------------------------------


async def test_beat_sensitivity_all_sensitive() -> None:
    def hash_fn(t: float, tl: Mapping[str, Any]) -> str:
        return _digest(t, _beat_starts(tl, "s-b"))

    report = await beat_sensitivity(FakePage(hash_fn=hash_fn), TIMELINE, "s-b")
    assert report.insensitive_beats == [] and not report.all_insensitive
    assert report.tested == [0, 1, 2]


async def test_beat_sensitivity_none_sensitive_when_times_are_hardcoded() -> None:
    report = await beat_sensitivity(FakePage(hash_fn=lambda t, tl: _digest(t)), TIMELINE, "s-b")
    assert report.insensitive_beats == [0, 1, 2]
    assert report.all_insensitive


async def test_beat_sensitivity_partial() -> None:
    def hash_fn(t: float, tl: Mapping[str, Any]) -> str:
        return _digest(t, _beat_starts(tl, "s-b")[0])

    report = await beat_sensitivity(FakePage(hash_fn=hash_fn), TIMELINE, "s-b")
    assert report.insensitive_beats == [1, 2]
    assert not report.all_insensitive


async def test_beat_sensitivity_skips_beats_too_close_to_the_end_and_restores_timeline() -> None:
    timeline = copy.deepcopy(TIMELINE)
    timeline["narration"][1]["beats"][2] = {"start": 11.6, "end": 11.9, "cue_text": "尾"}
    page = FakePage(hash_fn=lambda t, tl: _digest(t, _beat_starts(tl, "s-b")))
    page.timeline = timeline
    report = await beat_sensitivity(page, timeline, "s-b")
    assert report.skipped == [2]
    assert report.tested == [0, 1]
    assert page.timeline is timeline


async def test_beat_sensitivity_without_beats_tests_nothing() -> None:
    timeline = copy.deepcopy(TIMELINE)
    timeline["narration"][0]["beats"] = []
    page = FakePage()
    page.timeline = timeline
    report = await beat_sensitivity(page, timeline, "s-a")
    assert report.tested == [] and not report.all_insensitive


class _PoisoningPage(FakePage):
    def __init__(self) -> None:
        super().__init__(hash_fn=lambda t, tl: _digest(t))
        self.set_calls = 0
        self.calls_at_poison: list[int] = []

    async def set_timeline(self, timeline: Mapping[str, Any]) -> None:
        self.set_calls += 1
        await super().set_timeline(timeline)

    async def render_hash(self, t: float) -> str:
        self.poisoned = True
        self.calls_at_poison.append(self.set_calls)
        raise RenderTimeout(t, 10.0)


async def test_beat_sensitivity_does_not_touch_a_poisoned_page_in_its_cleanup() -> None:
    page = _PoisoningPage()
    with pytest.raises(RenderTimeout):
        await beat_sensitivity(page, TIMELINE, "s-b")
    assert page.set_calls == page.calls_at_poison[0]  # 页面作废后，清理阶段不再碰它
