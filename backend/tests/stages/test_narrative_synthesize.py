"""`stages.narrative.synthesize_tts`（设计 §5.2；计划 M3 T6）。

用 T4 的 `narrative_project` fixture 取一个"选题已定稿"的项目，直接往
工作区写 `narrative/narrative.json`（模拟 agent 已经写好的产物），再
用 monkeypatch 换掉 `synthesize_tts` 模块里的 `_ENGINE_FACTORY`（模块级
可替换的"缝"，测试用假引擎，不发真实网络请求），调用工具。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import pytest
from sqlalchemy import Engine

from studio.agent.tools import ToolContext, invoke_tool
from studio.engines.tts.base import TTSRequest, TTSResult, WordTimestamp
from studio.stages.narrative import synthesize_tts as synthesize_tts_module
from studio.stages.narrative.synthesize_tts import SYNTHESIZE_TTS_TOOL
from studio.workspace import BlobStore


class NarrativeProjectEnv(Protocol):
    project_id: str
    workdir: Path
    engine: Engine
    blobs: BlobStore


_NARRATIVE_DOC = {
    "scenes": [
        {
            "id": "s-hook",
            "narration": "甲乙",
            "visual_intent": "x",
            "beats": [
                {"cue_text": "甲", "visual_action": "x", "emphasis": "x", "transition": "reveal"},
                {"cue_text": "乙", "visual_action": "x", "emphasis": "x", "transition": "exit"},
            ],
        },
        {
            "id": "s-explain",
            "narration": "丙丁",
            "visual_intent": "x",
            "beats": [
                {
                    "cue_text": "丙",
                    "visual_action": "x",
                    "emphasis": "x",
                    "transition": "continue",
                },
                {"cue_text": "丁", "visual_action": "x", "emphasis": "x", "transition": "exit"},
            ],
        },
    ]
}


class FakeTTSEngine:
    """按 `request.text` 返回预设结果的测试替身；未预设的文本视为合成失败。"""

    engine_name = "fake"

    def __init__(self, responses: dict[str, TTSResult]) -> None:
        self._responses = responses

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        result = self._responses.get(request.text)
        if result is None:
            return TTSResult(
                success=False,
                output_path=None,
                duration_seconds=None,
                error_message=f"未预设的文本：{request.text}",
            )
        return result

    async def health_check(self) -> bool:
        return True


def _ok_result(text: str) -> TTSResult:
    chars = list(text)
    return TTSResult(
        success=True,
        output_path=None,
        duration_seconds=1.0,
        error_message=None,
        audio_bytes=f"AUDIO-{text}".encode(),
        word_timestamps=[
            WordTimestamp(word=chars[0], start_time=0.0, end_time=0.5),
            WordTimestamp(word=chars[1], start_time=0.5, end_time=1.0),
        ],
    )


def _write_narrative(env: NarrativeProjectEnv, doc: dict) -> None:
    narrative_dir = env.workdir / "narrative"
    narrative_dir.mkdir(parents=True, exist_ok=True)
    (narrative_dir / "narrative.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )


def _ctx(env: NarrativeProjectEnv) -> ToolContext:
    writes: list[tuple[str, str]] = []
    return ToolContext(
        project_id=env.project_id,
        stage="narrative",
        workdir=env.workdir,
        record_tool_write=lambda relpath, sha256: writes.append((relpath, sha256)),
        engine=env.engine,
    )


def _use_fake_engine(monkeypatch: pytest.MonkeyPatch, responses: dict[str, TTSResult]) -> None:
    monkeypatch.setattr(synthesize_tts_module, "_ENGINE_FACTORY", lambda: FakeTTSEngine(responses))


def _read_timing(env: NarrativeProjectEnv) -> dict:
    return json.loads((env.workdir / "narrative" / "timing.json").read_text(encoding="utf-8"))


def test_tool_is_scoped_to_narrative_stage() -> None:
    assert SYNTHESIZE_TTS_TOOL.stages == {"narrative"}


async def test_synthesizes_all_scenes_and_writes_timing_json(
    narrative_project: NarrativeProjectEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_narrative(narrative_project, _NARRATIVE_DOC)
    _use_fake_engine(monkeypatch, {"甲乙": _ok_result("甲乙"), "丙丁": _ok_result("丙丁")})

    result = await invoke_tool(SYNTHESIZE_TTS_TOOL, _ctx(narrative_project), {})

    assert result.is_error is False
    assert "s-hook（时长 1.00s，对齐覆盖率 100%）" in result.text
    timing = _read_timing(narrative_project)
    scenes = {scene["id"]: scene for scene in timing["scenes"]}
    assert [scene["id"] for scene in timing["scenes"]] == ["s-hook", "s-explain"]

    hook = scenes["s-hook"]
    assert hook["audio_path"] == "narrative/audio/s-hook.mp3"
    assert hook["audio_hash"].startswith("sha256:")
    assert hook["duration_seconds"] == 1.0
    assert hook["beats"] == [
        {"start_seconds": 0.0, "end_seconds": 0.5},
        {"start_seconds": 0.5, "end_seconds": 1.0},
    ]
    assert hook["word_timestamps"] == [
        {"word": "甲", "start_seconds": 0.0, "end_seconds": 0.5},
        {"word": "乙", "start_seconds": 0.5, "end_seconds": 1.0},
    ]
    assert hook["alignment_coverage"] == 1.0

    audio_bytes = (narrative_project.workdir / "narrative" / "audio" / "s-hook.mp3").read_bytes()
    assert audio_bytes == b"AUDIO-\xe7\x94\xb2\xe4\xb9\x99"


async def test_scene_ids_filters_to_requested_scenes_only(
    narrative_project: NarrativeProjectEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_narrative(narrative_project, _NARRATIVE_DOC)
    _use_fake_engine(monkeypatch, {"甲乙": _ok_result("甲乙"), "丙丁": _ok_result("丙丁")})
    await invoke_tool(SYNTHESIZE_TTS_TOOL, _ctx(narrative_project), {})
    before = _read_timing(narrative_project)["scenes"]
    explain_before = next(s for s in before if s["id"] == "s-explain")

    _use_fake_engine(monkeypatch, {"甲乙": _ok_result("甲乙2")})
    result = await invoke_tool(
        SYNTHESIZE_TTS_TOOL, _ctx(narrative_project), {"scene_ids": ["s-hook"]}
    )

    assert result.is_error is False
    after = _read_timing(narrative_project)["scenes"]
    explain_after = next(s for s in after if s["id"] == "s-explain")
    assert explain_after == explain_before

    hook_after = next(s for s in after if s["id"] == "s-hook")
    assert hook_after["audio_hash"] != next(s for s in before if s["id"] == "s-hook")["audio_hash"]


async def test_one_scene_failure_reports_error_but_others_still_written(
    narrative_project: NarrativeProjectEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_narrative(narrative_project, _NARRATIVE_DOC)
    _use_fake_engine(monkeypatch, {"丙丁": _ok_result("丙丁")})

    result = await invoke_tool(SYNTHESIZE_TTS_TOOL, _ctx(narrative_project), {})

    assert result.is_error is True
    assert "s-hook" in result.text
    timing = _read_timing(narrative_project)
    ids = {scene["id"] for scene in timing["scenes"]}
    assert ids == {"s-explain"}


async def test_invalid_narrative_json_is_rejected_before_any_synthesis(
    narrative_project: NarrativeProjectEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class _RecordingEngine(FakeTTSEngine):
        async def synthesize(self, request: TTSRequest) -> TTSResult:
            calls.append(request.text)
            return await super().synthesize(request)

    monkeypatch.setattr(synthesize_tts_module, "_ENGINE_FACTORY", lambda: _RecordingEngine({}))
    _write_narrative(narrative_project, {"scenes": []})

    result = await invoke_tool(SYNTHESIZE_TTS_TOOL, _ctx(narrative_project), {})

    assert result.is_error is True
    assert calls == []


async def test_unknown_scene_id_is_rejected(
    narrative_project: NarrativeProjectEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_narrative(narrative_project, _NARRATIVE_DOC)
    _use_fake_engine(monkeypatch, {"甲乙": _ok_result("甲乙"), "丙丁": _ok_result("丙丁")})

    result = await invoke_tool(
        SYNTHESIZE_TTS_TOOL, _ctx(narrative_project), {"scene_ids": ["s-missing"]}
    )

    assert result.is_error is True
    assert "s-missing" in result.text
