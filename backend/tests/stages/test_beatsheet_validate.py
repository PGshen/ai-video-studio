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
    check_beatsheet_mv,
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


# ---- music MV form (4A design 6.2) ----

MV_BPM = 120.0
MV_BAR = 4 * 60 / MV_BPM  # 2 s


def _analysis() -> dict[str, Any]:
    return {"bpm": MV_BPM, "offset": 0.0}


def _sections_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "sections": [
            {"id": "intro", "label": "前奏", "start": 0.0, "end": 8.0},
            {"id": "verse", "label": "主歌", "start": 8.0, "end": 24.0},
            {"id": "chorus", "label": "副歌", "start": 24.0, "end": 40.0},
        ]
    }
    doc.update(overrides)
    return doc


def _mv_doc() -> dict[str, Any]:
    return {
        "sections": [
            {
                "ref": "intro",
                "intent": "起",
                "energy": "low",
                "moments": [{"at": "1.1", "visual_action": "淡入"}],
            },
            {
                "ref": "verse",
                "intent": "蓄",
                "energy": "mid",
                "moments": [{"at": "8.4", "visual_action": "加速"}],
            },
            {"ref": "chorus", "intent": "爆", "energy": "peak", "moments": []},
        ]
    }


def _mv_with(index: int, **changes: Any) -> dict[str, Any]:
    doc = _mv_doc()
    doc["sections"][index].update(changes)
    return doc


def _mv(doc: Any, sections: Any = None, target: float | None = 40.0):
    return check_beatsheet_mv(
        doc, _sections_doc() if sections is None else sections, _analysis(), target_seconds=target
    )


def test_a_valid_mv_beatsheet_passes_and_reports_grid_and_total() -> None:
    result = _mv(_mv_doc())
    assert result.errors == [] and result.warnings == []
    assert result.total_seconds == pytest.approx(40.0)
    assert result.bpm == MV_BPM and result.section_count == 3


def test_mv_id_and_label_are_optional_and_id_must_equal_ref() -> None:
    assert _mv(_mv_with(0, id="intro", label="X")).errors == []
    assert _mv(_mv_with(0, id="other")).errors == ["段落 intro：id 'other' 必须与 ref 'intro' 一致"]


def test_mv_missing_ref_is_an_error() -> None:
    doc = _mv_doc()
    del doc["sections"][1]["ref"]
    assert "第 2 个段落缺少字符串 ref" in _mv(doc).errors[0]


def test_mv_unknown_and_duplicate_refs() -> None:
    errors = _mv(_mv_with(1, ref="bridge")).errors
    assert "段落 bridge：ref 在 music/sections.json 里不存在" in errors
    assert "还缺少 music/sections.json 的段落：verse" in errors
    dup = _mv_with(1, ref="intro")
    assert "段落 intro：ref 重复（每个段落只能引用一次）" in _mv(dup).errors


def test_mv_order_must_match_sections_json() -> None:
    doc = _mv_doc()
    doc["sections"][1], doc["sections"][2] = doc["sections"][2], doc["sections"][1]
    errors = _mv(doc).errors
    assert errors == ["段落 verse：顺序与 music/sections.json 不一致（应在 chorus 之前）"]


def test_mv_omitted_sections_are_named() -> None:
    doc = _mv_doc()
    del doc["sections"][0]
    del doc["sections"][1]
    errors = _mv(doc).errors
    assert "还缺少 music/sections.json 的段落：intro、chorus" in errors


def test_mv_bpm_and_bars_are_rejected() -> None:
    assert "MV 的节拍脚本不能写 bpm（节拍网格取自音乐）" in _mv({**_mv_doc(), "bpm": 120}).errors
    errors = _mv(_mv_with(0, bars=4)).errors
    assert errors == ["段落 intro：MV 的段落不能写 bars（段长以音乐为准）"]


def test_mv_moments_are_relative_to_the_section_and_must_fit() -> None:
    # intro is 8 s = 4 bars at 120 bpm
    assert _mv(_mv_with(0, moments=[{"at": "4.4", "visual_action": "a"}])).errors == []
    errors = _mv(_mv_with(0, moments=[{"at": "5.1", "visual_action": "a"}])).errors
    assert errors == ["段落 intro 的第 1 个 moment：at 5.1 没有落在本段内（本段只有 4.00 小节）"]
    late = _mv_with(
        0, moments=[{"at": "2.1", "visual_action": "a"}, {"at": "1.3", "visual_action": "b"}]
    )
    assert "比前一个 moment 早" in _mv(late).errors[0]
    bad = _mv(_mv_with(0, moments=[{"at": "x", "visual_action": "a"}])).errors[0]
    assert "不是合法的小节.拍写法" in bad


def test_mv_moment_conversion_uses_the_sections_json_bpm_override() -> None:
    # at 60 bpm a 8 s section is only 2 bars: 3.1 no longer fits, while at 120 bpm it would
    sections = _sections_doc(bpm=60)
    doc = _mv_with(0, moments=[{"at": "3.1", "visual_action": "a"}])
    doc["sections"][1]["moments"] = []
    assert _mv(doc, sections, target=None).errors == [
        "段落 intro 的第 1 个 moment：at 3.1 没有落在本段内（本段只有 2.00 小节）"
    ]
    assert _mv(doc, _sections_doc(), target=None).errors == []


def test_mv_energy_and_visual_action_and_intent_rules() -> None:
    assert "energy 必须是 low/mid/high/peak 之一" in _mv(_mv_with(0, energy="x")).errors[0]
    empty = _mv(_mv_with(0, moments=[{"at": "1.1", "visual_action": " "}], intent=""))
    assert empty.errors == []
    assert len(empty.warnings) == 2
    assert "intent 为空" in empty.warnings[0] and "visual_action 为空" in empty.warnings[1]


def test_mv_total_uses_the_section_span_or_explicit_range() -> None:
    result = _mv(_mv_doc(), target=30.0)
    assert result.errors == [] and result.warnings == [
        "总时长 40.00 秒与目标时长 30 秒相差 33%，超过 15%"
    ]
    far = _mv(_mv_doc(), target=20.0)
    assert far.errors == ["总时长 40.00 秒与目标时长 20 秒相差 100%，超过 40%"]
    ranged = _sections_doc(range={"start": 0.0, "end": 40.0})
    assert _mv(_mv_doc(), ranged).total_seconds == pytest.approx(40.0)
    assert _mv(_mv_doc(), target=None).warnings == [
        "没有读到 upstream/concept/brief.md 的目标时长，无法核对总时长"
    ]


@pytest.mark.parametrize("doc", [[], "x", {"sections": []}, {"sections": "x"}])
def test_mv_malformed_beatsheet_is_an_error_not_an_exception(doc: Any) -> None:
    assert _mv(doc).errors


@pytest.mark.parametrize(
    "sections",
    [[], {"sections": "x"}, {"sections": [{"id": "a"}]}, _sections_doc(bpm="fast")],
)
def test_mv_malformed_upstream_sections_is_an_error_not_an_exception(sections: Any) -> None:
    result = check_beatsheet_mv(_mv_doc(), sections, _analysis(), target_seconds=None)
    assert result.errors and all("music/sections.json" in e for e in result.errors[:1])


def test_mv_malformed_analysis_is_an_error_not_an_exception() -> None:
    result = check_beatsheet_mv(_mv_doc(), _sections_doc(), {"bpm": "x"}, target_seconds=None)
    assert result.errors and "music/analysis.json" in result.errors[0]


def _write_mv(workdir: Path, doc: Any, sections: Any = None, analysis: Any = None) -> None:
    (workdir / "beatsheet").mkdir(exist_ok=True)
    (workdir / "beatsheet" / "beatsheet.json").write_text(json.dumps(doc), encoding="utf-8")
    (workdir / "upstream" / "music").mkdir(parents=True, exist_ok=True)
    (workdir / "upstream" / "music" / "sections.json").write_text(
        json.dumps(_sections_doc() if sections is None else sections), encoding="utf-8"
    )
    if analysis is not False:
        (workdir / "upstream" / "music" / "analysis.json").write_text(
            json.dumps(_analysis() if analysis is None else analysis), encoding="utf-8"
        )
    (workdir / "upstream" / "concept").mkdir(parents=True, exist_ok=True)
    (workdir / "upstream" / "concept" / "brief.md").write_text(
        "# 简报\n\n目标时长：40 秒\n", encoding="utf-8"
    )


def test_workspace_dispatches_to_mv_when_upstream_sections_exist(tmp_path: Path) -> None:
    _write_mv(tmp_path, _mv_doc())
    result = check_workspace(tmp_path)
    assert result.errors == [] and result.bpm == MV_BPM and result.section_count == 3
    assert result.total_seconds == pytest.approx(40.0)


def test_workspace_without_upstream_sections_stays_a_reel(tmp_path: Path) -> None:
    (tmp_path / "beatsheet").mkdir()
    (tmp_path / "beatsheet" / "beatsheet.json").write_text(json.dumps(_mv_doc()), encoding="utf-8")
    assert any("BPM" in e for e in check_workspace(tmp_path).errors)


def test_workspace_mv_with_corrupt_or_missing_upstream_files(tmp_path: Path) -> None:
    _write_mv(tmp_path, _mv_doc(), analysis=False)
    errors = check_workspace(tmp_path).errors
    assert errors == ["upstream/music/analysis.json 不存在（音乐阶段还没有定稿分析）"]
    (tmp_path / "upstream" / "music" / "analysis.json").write_text("{oops", encoding="utf-8")
    assert (
        check_workspace(tmp_path)
        .errors[0]
        .startswith("upstream/music/analysis.json 不是合法的 JSON")
    )
    (tmp_path / "upstream" / "music" / "analysis.json").write_text(
        json.dumps(_analysis()), encoding="utf-8"
    )
    (tmp_path / "upstream" / "music" / "sections.json").write_text("{oops", encoding="utf-8")
    assert (
        check_workspace(tmp_path)
        .errors[0]
        .startswith("upstream/music/sections.json 不是合法的 JSON")
    )


async def test_mv_tool_runs_through_invoke(tmp_path: Path) -> None:
    _write_mv(tmp_path, _mv_doc())
    result = await invoke_tool(VALIDATE_BEATSHEET_TOOL, _ctx(tmp_path), {})
    assert not result.is_error
    assert "3 个段落，BPM 120，总时长 40.00 秒" in result.text
