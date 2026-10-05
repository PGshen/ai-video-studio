"""`validate_beatsheet`：节拍脚本的校验（子项目 3 设计 §6.2）。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.beatsheet.validate_beatsheet import (
    VALIDATE_BEATSHEET_TOOL,
    check_beatsheet,
    check_workspace,
)

BPM = 128.0
BAR = 4 * 60 / BPM


def _doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "bpm": BPM,
        "sections": [
            {
                "id": "s1-intro",
                "label": "INTRO",
                "bars": 2,
                "intent": "起",
                "energy": "low",
                "moments": [{"at": "1.1", "visual_action": "标题淡入"}],
            },
            {
                "id": "s2-build",
                "label": "BUILD",
                "bars": 2,
                "intent": "蓄",
                "energy": "mid",
                "moments": [{"at": "2.1", "visual_action": "加速"}],
            },
            {
                "id": "s3-drop",
                "label": "DROP",
                "bars": 2,
                "intent": "爆",
                "energy": "peak",
                "moments": [],
            },
        ],
    }
    doc.update(overrides)
    return doc


def _with_section(index: int, **changes: Any) -> dict[str, Any]:
    doc = _doc()
    doc["sections"][index].update(changes)
    return doc


def test_a_valid_beatsheet_passes_and_reports_the_total() -> None:
    result = check_beatsheet(_doc(), target_seconds=11.25)
    assert result.errors == [] and result.warnings == []
    assert result.total_seconds == pytest.approx(6 * BAR)
    assert result.bpm == BPM and result.section_count == 3


@pytest.mark.parametrize("bpm", [60, 200, 128.5])
def test_bpm_inside_the_range_is_fine(bpm: float) -> None:
    doc = _doc(bpm=bpm)
    doc["sections"][0]["bars"] = 8  # keep the total long enough for the slowest tempo
    assert not any("BPM" in e for e in check_beatsheet(doc, target_seconds=None).errors)


@pytest.mark.parametrize("bpm", [59, 201, "fast", None, True])
def test_bpm_outside_the_range_or_not_a_number_is_an_error(bpm: Any) -> None:
    assert any("BPM" in e for e in check_beatsheet(_doc(bpm=bpm), target_seconds=None).errors)


@pytest.mark.parametrize(
    ("doc", "needle"),
    [
        ([], "对象"),
        (_doc(sections=[]), "段落"),
        (_doc(sections="x"), "段落"),
        (_doc(sections=[copy.deepcopy(_doc()["sections"][0]) for _ in range(13)]), "12"),
        (_with_section(0, id="s 1"), "id"),
        (_with_section(0, id=""), "id"),
        (_with_section(1, id="s1-intro"), "重复"),
        (_with_section(0, bars=0), "bars"),
        (_with_section(0, bars=2.5), "bars"),
        (_with_section(0, bars="2"), "bars"),
        (_with_section(0, bars=True), "bars"),
        (_with_section(0, energy="loud"), "energy"),
        (_with_section(0, energy=None), "energy"),
        (_with_section(0, moments=[{"at": "x.y", "visual_action": "a"}]), "小节.拍"),
        (_with_section(0, moments=[{"at": "3.1", "visual_action": "a"}]), "落在本段内"),
        (_with_section(0, moments=[{"at": "2.5", "visual_action": "a"}]), "落在本段内"),
        (
            _with_section(
                0,
                moments=[{"at": "2.1", "visual_action": "a"}, {"at": "1.3", "visual_action": "b"}],
            ),
            "顺序",
        ),
        (_with_section(0, moments=[{"visual_action": "a"}]), "at"),
        (_with_section(0, moments="x"), "moments"),
    ],
)
def test_structural_errors_are_reported(doc: Any, needle: str) -> None:
    errors = check_beatsheet(doc, target_seconds=None).errors
    assert any(needle in e for e in errors), errors


def test_moments_in_the_last_bar_and_at_the_same_time_are_fine() -> None:
    doc = _with_section(
        0,
        moments=[
            {"at": "2.4", "visual_action": "a"},
            {"at": "2.4", "visual_action": "b"},
            {"at": "2.4+1/16", "visual_action": "c"},
        ],
    )
    assert check_beatsheet(doc, target_seconds=None).errors == []


def test_total_duration_bounds() -> None:
    short = _doc()
    short["sections"] = short["sections"][:2]  # 4 bars = 7.5 s
    assert any("8" in e and "时长" in e for e in check_beatsheet(short, target_seconds=None).errors)
    long = _doc()
    long["sections"][0]["bars"] = 100  # 100 bars = 187.5 s
    assert any("180" in e for e in check_beatsheet(long, target_seconds=None).errors)
    ok = _doc()
    ok["sections"] = ok["sections"][:2]
    ok["sections"][0]["bars"] = 3  # 5 bars = 9.4 s
    assert not any("时长" in e for e in check_beatsheet(ok, target_seconds=None).errors)


@pytest.mark.parametrize(
    ("target", "level"),
    [
        (11.25, None),
        (12.0, None),
        (14.0, "warning"),
        (9.5, "warning"),
        (20.0, "error"),
        (7.0, "error"),
    ],
)
def test_deviation_from_the_target_duration(target: float, level: str | None) -> None:
    result = check_beatsheet(_doc(), target_seconds=target)  # total is 11.25 s
    hit_error = any("目标时长" in e for e in result.errors)
    hit_warning = any("目标时长" in w for w in result.warnings)
    assert (hit_error, hit_warning) == (level == "error", level == "warning")


def test_missing_target_is_only_a_warning() -> None:
    result = check_beatsheet(_doc(), target_seconds=None)
    assert result.errors == [] and any("目标时长" in w for w in result.warnings)


def test_empty_intent_label_and_action_are_warnings() -> None:
    doc = _with_section(0, intent="", moments=[{"at": "1.1", "visual_action": ""}])
    del doc["sections"][1]["label"]
    result = check_beatsheet(doc, target_seconds=11.25)
    assert result.errors == []
    assert any("intent" in w for w in result.warnings)
    assert any("visual_action" in w for w in result.warnings)


def test_several_errors_are_listed_together() -> None:
    doc = _doc(bpm=10)
    doc["sections"][0]["bars"] = 0
    doc["sections"][1]["energy"] = "x"
    assert len(check_beatsheet(doc, target_seconds=None).errors) >= 3


# ---- workspace + tool ------------------------------------------------------------


def _ctx(workdir: Path) -> ToolContext:
    return ToolContext(
        project_id="p", stage="beatsheet", workdir=workdir, record_tool_write=lambda *_: None
    )


def _write(workdir: Path, relpath: str, text: str) -> None:
    path = workdir / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_workspace_reads_the_target_from_the_upstream_brief(tmp_path: Path) -> None:
    _write(tmp_path, "beatsheet/beatsheet.json", json.dumps(_doc()))
    _write(tmp_path, "upstream/concept/brief.md", "## 目标时长\n\n20 秒\n")
    result = check_workspace(tmp_path)
    assert any("目标时长" in e for e in result.errors)  # 11.25 s against 20 s is > 40 %


def test_workspace_missing_or_broken_files(tmp_path: Path) -> None:
    assert any("beatsheet.json" in e for e in check_workspace(tmp_path).errors)
    _write(tmp_path, "beatsheet/beatsheet.json", "{nope")
    assert any("JSON" in e for e in check_workspace(tmp_path).errors)


async def test_tool_reports_pass_and_errors(tmp_path: Path) -> None:
    assert VALIDATE_BEATSHEET_TOOL.stages == {"beatsheet"}
    _write(tmp_path, "beatsheet/beatsheet.json", json.dumps(_doc()))
    _write(tmp_path, "upstream/concept/brief.md", "## 目标时长\n\n11 秒\n")
    ok = await invoke_tool(VALIDATE_BEATSHEET_TOOL, _ctx(tmp_path), {})
    assert not ok.is_error and "通过" in ok.text and "11.25" in ok.text
    _write(tmp_path, "beatsheet/beatsheet.json", json.dumps(_doc(bpm=10)))
    bad = await invoke_tool(VALIDATE_BEATSHEET_TOOL, _ctx(tmp_path), {})
    assert bad.is_error and "BPM" in bad.text
