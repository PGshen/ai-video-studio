"""`stages.narrative.validate_narrative`（设计 §5.2；计划 M3 T5）。

用 T4 的 `narrative_project` fixture（顶层 `conftest.py`）取一个"选题已
定稿"的项目，直接往工作区写 `narrative/narrative.json`（绕过
`WriteScope`，模拟"测试提前准备好的文件"，`fixtures/animation/seed.py`
对 `narrative/` 也是同样做法），再调用工具。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine

from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.narrative.validate_narrative import VALIDATE_NARRATIVE_TOOL
from studio.workspace import BlobStore


class NarrativeProjectEnv(Protocol):
    """`conftest.NarrativeProjectEnv` 的结构类型（鸭子类型），理由同
    `tests/stages/test_animation_validate.py` 的 `AnimationProjectEnv`。
    """

    project_id: str
    workdir: Path
    engine: Engine
    blobs: BlobStore


_VALID_DOC = {
    "scenes": [
        {
            "id": "s-hook",
            "narration": "甲乙丙丁",
            "visual_intent": "x",
            "beats": [
                {"cue_text": "甲乙", "visual_action": "x", "emphasis": "x", "transition": "reveal"},
                {"cue_text": "丙丁", "visual_action": "x", "emphasis": "x", "transition": "exit"},
            ],
        }
    ]
}


def _write_narrative(env: NarrativeProjectEnv, doc: dict) -> None:
    narrative_dir = env.workdir / "narrative"
    narrative_dir.mkdir(parents=True, exist_ok=True)
    (narrative_dir / "narrative.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )


def _ctx(env: NarrativeProjectEnv) -> ToolContext:
    return ToolContext(
        project_id=env.project_id,
        stage="narrative",
        workdir=env.workdir,
        record_tool_write=lambda relpath, sha256: None,
    )


def test_tool_is_scoped_to_narrative_stage() -> None:
    assert VALIDATE_NARRATIVE_TOOL.stages == {"narrative"}


async def test_missing_file_reports_error(narrative_project: NarrativeProjectEnv) -> None:
    result = await invoke_tool(VALIDATE_NARRATIVE_TOOL, _ctx(narrative_project), {})

    assert result.is_error is True
    assert "narrative.json" in result.text


async def test_invalid_json_reports_error(narrative_project: NarrativeProjectEnv) -> None:
    narrative_dir = narrative_project.workdir / "narrative"
    narrative_dir.mkdir(parents=True, exist_ok=True)
    (narrative_dir / "narrative.json").write_text("{not valid json", encoding="utf-8")

    result = await invoke_tool(VALIDATE_NARRATIVE_TOOL, _ctx(narrative_project), {})

    assert result.is_error is True
    assert "JSON" in result.text


async def test_valid_document_passes(narrative_project: NarrativeProjectEnv) -> None:
    _write_narrative(narrative_project, _VALID_DOC)

    result = await invoke_tool(VALIDATE_NARRATIVE_TOOL, _ctx(narrative_project), {})

    assert result.is_error is False
    assert "1" in result.text


async def test_invalid_document_points_at_scene_id(narrative_project: NarrativeProjectEnv) -> None:
    broken = {
        "scenes": [
            {
                "id": "s-broken",
                "narration": "甲乙丙丁",
                "visual_intent": "x",
                "beats": [
                    {
                        "cue_text": "甲乙",
                        "visual_action": "x",
                        "emphasis": "x",
                        "transition": "boom",
                    }
                ],
            }
        ]
    }
    _write_narrative(narrative_project, broken)

    result = await invoke_tool(VALIDATE_NARRATIVE_TOOL, _ctx(narrative_project), {})

    assert result.is_error is True
    assert "s-broken" in result.text
