"""`BeatsheetStage`：协议值、可写范围、定稿条件、提示词（子项目 3 设计 §6.2）。"""

from __future__ import annotations

import json
from pathlib import Path

from studio.agent.stage import StageDefinition, StageRegistry, upstream_of
from studio.stages.beatsheet import STAGE
from studio.stages.concept import STAGE as CONCEPT
from studio.stages.pipeline import ProjectKind, build_pipeline
from studio.workspace.scope import is_writable


def _write_sheet(workdir: Path, doc: dict) -> None:
    (workdir / "beatsheet").mkdir(exist_ok=True)
    (workdir / "beatsheet" / "beatsheet.json").write_text(json.dumps(doc), encoding="utf-8")


_GOOD = {
    "bpm": 128,
    "sections": [
        {"id": "a", "label": "A", "bars": 3, "intent": "i", "energy": "low", "moments": []},
        {"id": "b", "label": "B", "bars": 3, "intent": "i", "energy": "high", "moments": []},
    ],
}


def test_stage_protocol_values() -> None:
    assert isinstance(STAGE, StageDefinition)
    assert STAGE.name == "beatsheet" and STAGE.allow_web is False and STAGE.workspaceless is False
    assert STAGE.reads() == ["concept", "music"] and STAGE.artifact_dirs() == ["beatsheet"]
    scope = STAGE.write_scope()
    assert is_writable(scope, "beatsheet/beatsheet.json") is True
    assert is_writable(scope, "concept/brief.md") is False
    assert {t.name for t in STAGE.tools()} == {"validate_beatsheet", "suggest_upstream_change"}


def test_in_a_motion_reel_only_the_concept_is_upstream() -> None:
    registry = StageRegistry()
    registry.register(CONCEPT)
    registry.register(STAGE)
    pipeline = build_pipeline(ProjectKind("html", False, "synth"))
    assert upstream_of(pipeline, registry, "beatsheet") == ["concept"]


def test_finalize_is_blocked_by_validation_errors_only(tmp_path: Path) -> None:
    assert STAGE.finalize_blockers(tmp_path)  # nothing written yet
    _write_sheet(tmp_path, {**_GOOD, "bpm": 10})
    assert any("BPM" in blocker for blocker in STAGE.finalize_blockers(tmp_path))
    _write_sheet(tmp_path, _GOOD)  # warnings (no target duration) do not block
    assert STAGE.finalize_blockers(tmp_path) == []


def test_status_summary_names_sections_bpm_and_length(tmp_path: Path) -> None:
    _write_sheet(tmp_path, _GOOD)
    summary = STAGE.status_summary(tmp_path)
    assert "2 个段落" in summary and "128" in summary and "11.2" in summary


def test_prompt_states_the_contract() -> None:
    prompt = STAGE.system_prompt()
    for needle in (
        "beatsheet/beatsheet.json",
        "validate_beatsheet",
        "小节.拍",
        "energy",
        "bars",
        "upstream/concept/brief.md",
        "low",
        "peak",
        "moments",
    ):
        assert needle in prompt


def test_mv_form_finalize_and_status_follow_the_upstream_sections(tmp_path: Path) -> None:
    (tmp_path / "upstream" / "music").mkdir(parents=True)
    (tmp_path / "upstream" / "music" / "sections.json").write_text(
        json.dumps(
            {
                "sections": [
                    {"id": "a", "label": "A", "start": 0.0, "end": 16.0},
                    {"id": "b", "label": "B", "start": 16.0, "end": 32.0},
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "upstream" / "music" / "analysis.json").write_text(
        json.dumps({"bpm": 120, "offset": 0.0}), encoding="utf-8"
    )
    _write_sheet(
        tmp_path,
        {
            "sections": [
                {"ref": "a", "intent": "i", "energy": "low", "moments": []},
                {"ref": "b", "intent": "i", "energy": "high", "moments": []},
            ]
        },
    )
    assert STAGE.finalize_blockers(tmp_path) == []
    assert STAGE.status_summary(tmp_path) == "2 个段落，BPM 120，总时长 32.00 秒"
    _write_sheet(tmp_path, {"sections": [{"ref": "a", "intent": "i", "energy": "low"}]})
    assert STAGE.finalize_blockers(tmp_path) == ["还缺少 music/sections.json 的段落：b"]
    assert STAGE.status_summary(tmp_path) == "1 个段落，BPM 120，总时长 32.00 秒"


def test_prompt_has_a_music_video_section() -> None:
    prompt = STAGE.system_prompt()
    for needle in ("音乐 MV", "ref", "upstream/music/sections.json", "analysis.json"):
        assert needle in prompt
