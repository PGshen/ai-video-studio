"""`check_sections` / `validate_sections` (4A T5): sections.json against analysis.json."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.music.validate_sections import VALIDATE_SECTIONS_TOOL, check_sections

# 120 BPM, first downbeat at 0.5 s: downbeats at 0.5, 2.5, 4.5, ... (a bar is 2 s)
ANALYSIS: dict[str, Any] = {
    "source_hash": "h" * 64,
    "duration": 40.0,
    "bpm": 120.0,
    "offset": 0.5,
    "hop": 0.1,
    "energy": [0.5] * 400,
    "residual_ms": 5.0,
    "confidence": 0.9,
}


def doc(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sections": [
            {"id": "intro", "label": "Intro", "start": 0.5, "end": 8.5},
            {"id": "verse", "label": "Verse", "start": 8.5, "end": 24.5},
        ]
    }
    base.update(extra)
    return base


def errors_of(d: Any, analysis: Any = None) -> list[str]:
    return check_sections(d, ANALYSIS if analysis is None else analysis).errors


def test_valid_document_passes() -> None:
    result = check_sections(doc(), ANALYSIS)
    assert result.ok and result.errors == [] and result.section_count == 2


def test_valid_with_explicit_range_equal_to_span() -> None:
    assert check_sections(doc(range={"start": 0.5, "end": 24.5}), ANALYSIS).ok


def test_range_must_equal_the_section_span() -> None:
    errors = errors_of(doc(range={"start": 0.5, "end": 28.5}))
    assert any("range" in e and "段落" in e for e in errors)
    assert errors_of(doc(range={"start": 2.5, "end": 24.5}))


def test_range_must_be_aligned_to_downbeats() -> None:
    # Section span and range agree (1.0 → 24.5) so only the alignment rule can object.
    d = doc(range={"start": 1.0, "end": 24.5})
    d["sections"][0]["start"] = 1.0
    errors = errors_of(d)
    assert any("range 的起点" in e and "强拍" in e and "0.5" in e for e in errors)
    d = doc(range={"start": 0.5, "end": 25.0})
    d["sections"][1]["end"] = 25.0
    assert any("range 的终点" in e and "强拍" in e for e in errors_of(d))


def test_gap_between_sections_is_an_error() -> None:
    d = doc()
    d["sections"][1]["start"] = 10.5
    assert any("空隙" in e for e in errors_of(d))


def test_overlap_is_an_error() -> None:
    d = doc()
    d["sections"][1]["start"] = 6.5
    assert any("重叠" in e for e in errors_of(d))


def test_out_of_order_is_an_error() -> None:
    d = doc()
    d["sections"].reverse()
    assert any("顺序" in e for e in errors_of(d))


def test_start_must_be_before_end() -> None:
    d = doc()
    d["sections"][0]["end"] = 0.5
    assert any("start" in e or "起点" in e for e in errors_of(d))


def test_ids_must_be_valid_and_unique() -> None:
    d = doc()
    d["sections"][1]["id"] = "intro"
    assert any("重复" in e for e in errors_of(d))
    d = doc()
    d["sections"][0]["id"] = "bad id!"
    assert any("id" in e for e in errors_of(d))


def test_sections_must_stay_within_the_audio() -> None:
    d = doc()
    d["sections"][1]["end"] = 44.5
    assert any("超出" in e for e in errors_of(d))
    d = doc()
    d["sections"][0]["start"] = -1.5
    assert any("超出" in e for e in errors_of(d))


def _shifted(target: str, shift: float) -> dict[str, Any]:
    """Valid doc with one boundary moved by `shift` seconds (a shared one moves on both sides)."""
    d = doc(range={"start": 0.5, "end": 24.5}) if target.startswith("range") else doc()
    sections, rng = d["sections"], d.get("range") or {}
    if target == "first_start":
        sections[0]["start"] += shift
    elif target == "middle":
        sections[0]["end"] += shift
        sections[1]["start"] += shift
    elif target == "last_end":
        sections[1]["end"] += shift
    elif target == "range_start":
        rng["start"] += shift
        sections[0]["start"] += shift
    elif target == "range_end":
        rng["end"] += shift
        sections[1]["end"] += shift
    return d


_WORD = {
    "first_start": "起点",
    "middle": "终点",
    "last_end": "终点",
    "range_start": "range 的起点",
    "range_end": "range 的终点",
}


@pytest.mark.parametrize("target", list(_WORD))
@pytest.mark.parametrize(
    ("shift", "ok"),
    [(-0.029, True), (0.029, True), (-0.03, True), (0.03, True), (-0.031, False), (0.031, False)],
)
def test_alignment_tolerance_is_30_ms(target: str, shift: float, ok: bool) -> None:
    errors = errors_of(_shifted(target, shift))
    assert (errors == []) is ok, errors
    if not ok:
        assert any(_WORD[target] in e and "强拍" in e for e in errors)


def test_last_end_must_be_on_a_downbeat() -> None:
    d = doc()
    d["sections"][1]["end"] = 25.5  # mid-bar
    assert any("verse 的终点" in e and "强拍" in e and "24.5" in e for e in errors_of(d))


def test_misaligned_start_names_the_nearest_downbeat() -> None:
    d = doc()
    d["sections"][1]["start"] = 9.4
    d["sections"][0]["end"] = 9.4
    errors = errors_of(d)
    assert any("8.5" in e and "强拍" in e for e in errors)


def _bar_doc(*bounds: float) -> dict[str, Any]:
    names = "abcdefgh"
    return {
        "sections": [
            {"id": names[i], "label": names[i].upper(), "start": start, "end": end}
            for i, (start, end) in enumerate(zip(bounds, bounds[1:], strict=False))
        ]
    }


_GRID_AT_ZERO = {**ANALYSIS, "offset": 0.0}  # 120 BPM: downbeats at 0, 2, 4, ...


def test_a_section_whose_ends_snap_to_the_same_downbeat_is_an_error() -> None:
    # b is 60 ms long: both its ends are within 30 ms of the downbeat at 2 s.
    errors = check_sections(_bar_doc(0.0, 1.97, 2.03, 4.0), _GRID_AT_ZERO).errors
    assert errors == [
        "段落 b 不足一小节：1.97→2.03 s 的起点和终点吸附到同一个强拍 2 s，"
        "每个段落至少要跨一小节（起止落在不同的强拍上）"
    ]


def test_a_one_bar_section_passes() -> None:
    assert check_sections(_bar_doc(0.0, 2.0, 4.0, 10.0), _GRID_AT_ZERO).errors == []
    # Tolerance on both sides still leaves a different downbeat at each end.
    assert check_sections(_bar_doc(0.0, 2.03, 3.97, 10.0), _GRID_AT_ZERO).errors == []


def test_overrides_move_the_grid() -> None:
    # bpm 60 -> bar 4 s; offset 0 -> downbeats at 0, 4, 8, ...
    d = {
        "bpm": 60,
        "offset": 0,
        "sections": [{"id": "a", "label": "A", "start": 4.0, "end": 12.0}],
    }
    assert check_sections(d, ANALYSIS).ok
    d["sections"][0]["start"] = 0.5
    assert not check_sections(d, ANALYSIS).ok


@pytest.mark.parametrize("bpm", [10, 500, 0, -5, float("nan"), float("inf"), True, "120"])
def test_bpm_override_is_bounds_checked(bpm: Any) -> None:
    errors = errors_of(doc(bpm=bpm))
    assert any("bpm" in e.lower() for e in errors)


@pytest.mark.parametrize("offset", [-1, 40.0, 1e12, float("nan"), float("inf"), True, "0"])
def test_offset_override_is_bounds_checked(offset: Any) -> None:
    errors = errors_of(doc(offset=offset))
    assert any("offset" in e for e in errors)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        "x",
        3,
        {},
        {"sections": None},
        {"sections": []},
        {"sections": "x"},
        {"sections": [None]},
        {"sections": [{}]},
        {"sections": [{"id": 3, "start": 0.5, "end": 2.5}]},
        {"sections": [{"id": "a", "start": "0.5", "end": 2.5}]},
        {"sections": [{"id": "a", "start": True, "end": 2.5}]},
        {"sections": [{"id": "a", "start": 0.5, "end": float("nan")}]},
        {"sections": [{"id": "a", "start": 0.5}]},
        {"sections": [{"id": "a", "start": 0.5, "end": 2.5}], "range": "x"},
        {"sections": [{"id": "a", "start": 0.5, "end": 2.5}], "range": {"start": 0.5}},
        {"sections": [{"id": "a", "start": 0.5, "end": 2.5}], "range": {"start": True, "end": 2}},
    ],
)
def test_malformed_documents_become_errors(bad: Any) -> None:
    result = check_sections(bad, ANALYSIS)
    assert not result.ok and result.errors


@pytest.mark.parametrize(
    "analysis",
    [None, [], {}, {"duration": "x"}, {"duration": True, "bpm": 120, "offset": 0}],
)
def test_malformed_analysis_becomes_errors(analysis: Any) -> None:
    result = check_sections(doc(), analysis)
    assert not result.ok and result.errors


def test_empty_label_is_only_a_warning() -> None:
    d = copy.deepcopy(doc())
    d["sections"][0]["label"] = " "
    result = check_sections(d, ANALYSIS)
    assert result.ok and any("label" in w for w in result.warnings)


def test_does_not_mutate_inputs() -> None:
    d = doc()
    before = copy.deepcopy(d)
    check_sections(d, ANALYSIS)
    assert d == before


# --- tool -------------------------------------------------------------------------------------


def _ctx(workdir: Path) -> ToolContext:
    return ToolContext(
        project_id="p", stage="music", workdir=workdir, record_tool_write=lambda rel, digest: None
    )


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "source.mp3").write_bytes(b"x")  # the tool only runs in the import form
    return tmp_path


def test_tool_registration() -> None:
    assert VALIDATE_SECTIONS_TOOL.name == "validate_sections"
    assert VALIDATE_SECTIONS_TOOL.stages == {"music"}


async def test_tool_requires_analysis_first(workdir: Path) -> None:
    (workdir / "music" / "sections.json").write_text(json.dumps(doc()))
    result = await invoke_tool(VALIDATE_SECTIONS_TOOL, _ctx(workdir), {})
    assert result.is_error and "请先 analyze_music" in result.text


async def test_tool_requires_sections_file(workdir: Path) -> None:
    (workdir / "music" / "analysis.json").write_text(json.dumps(ANALYSIS))
    result = await invoke_tool(VALIDATE_SECTIONS_TOOL, _ctx(workdir), {})
    assert result.is_error and "sections.json" in result.text


async def test_tool_reports_invalid_json(workdir: Path) -> None:
    (workdir / "music" / "analysis.json").write_text(json.dumps(ANALYSIS))
    (workdir / "music" / "sections.json").write_text("{nope")
    result = await invoke_tool(VALIDATE_SECTIONS_TOOL, _ctx(workdir), {})
    assert result.is_error and "JSON" in result.text


async def test_tool_passes_and_fails(workdir: Path) -> None:
    (workdir / "music" / "analysis.json").write_text(json.dumps(ANALYSIS))
    (workdir / "music" / "sections.json").write_text(json.dumps(doc()))
    ok = await invoke_tool(VALIDATE_SECTIONS_TOOL, _ctx(workdir), {})
    assert not ok.is_error and "校验通过" in ok.text and "2 个段落" in ok.text
    bad = doc()
    bad["sections"][1]["start"] = 10.5
    (workdir / "music" / "sections.json").write_text(json.dumps(bad))
    failed = await invoke_tool(VALIDATE_SECTIONS_TOOL, _ctx(workdir), {})
    assert failed.is_error and "空隙" in failed.text
