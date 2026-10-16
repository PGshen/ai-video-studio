"""`stages.common.narration.tts`：完全自由阶段的通用配音工具（open-mode 设计 §4.2）。

TTS 引擎用替身（换掉模块级的 `_ENGINE_FACTORY`），不发真实请求。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pytest
from sqlalchemy import Engine

from studio.agent.tools import ToolContext, invoke_tool
from studio.db.repo.projects import update_project_settings
from studio.engines.tts.base import TTSRequest, TTSResult
from studio.engines.tts.voice_map import DEFAULT_SPEED, DEFAULT_VOICE
from studio.stages.common.narration import tts as tts_module
from studio.stages.common.narration.tts import TTS_TOOL


class NarrativeProjectEnv(Protocol):
    project_id: str
    workdir: Path
    engine: Engine


class _RecordingEngine:
    engine_name = "fake"

    def __init__(self, *, fail: bool = False) -> None:
        self.requests: list[TTSRequest] = []
        self._fail = fail

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        self.requests.append(request)
        if self._fail:
            return TTSResult(
                success=False, output_path=None, duration_seconds=None, error_message="限流"
            )
        return TTSResult(
            success=True,
            output_path=None,
            duration_seconds=1.25,
            error_message=None,
            audio_bytes=b"MP3-" + request.text.encode(),
        )

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def tts_engine(monkeypatch: pytest.MonkeyPatch) -> _RecordingEngine:
    engine = _RecordingEngine()
    monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda _voices: engine)
    return engine


def _ctx(env: NarrativeProjectEnv, writes: list[str] | None = None) -> ToolContext:
    recorded = writes if writes is not None else []
    return ToolContext(
        project_id=env.project_id,
        stage="open",
        workdir=env.workdir,
        record_tool_write=lambda relpath, _sha: recorded.append(relpath),
        engine=env.engine,
    )


def test_tool_belongs_to_the_open_stage_only() -> None:
    assert TTS_TOOL.name == "tts"
    assert TTS_TOOL.stages == {"open"}


async def test_writes_audio_where_the_agent_asks(
    narrative_project: NarrativeProjectEnv, tts_engine: _RecordingEngine
) -> None:
    writes: list[str] = []

    result = await invoke_tool(
        TTS_TOOL,
        _ctx(narrative_project, writes),
        {"text": "你好", "out_path": "deep/new/dir/a.mp3"},
    )

    assert not result.is_error, result.text
    assert (narrative_project.workdir / "deep/new/dir/a.mp3").read_bytes() == "MP3-你好".encode()
    assert writes == ["deep/new/dir/a.mp3"]
    assert "deep/new/dir/a.mp3" in result.text and "1.25" in result.text


async def test_uses_project_voice_and_speed_by_default(
    narrative_project: NarrativeProjectEnv, tts_engine: _RecordingEngine
) -> None:
    update_project_settings(
        narrative_project.engine,
        narrative_project.project_id,
        {"voice": "温柔女声", "speech_rate": 1.2},
    )

    await invoke_tool(TTS_TOOL, _ctx(narrative_project), {"text": "a", "out_path": "a.mp3"})

    (request,) = tts_engine.requests
    assert (request.voice, request.speed) == ("温柔女声", 1.2)


async def test_falls_back_to_builtin_voice(
    narrative_project: NarrativeProjectEnv, tts_engine: _RecordingEngine
) -> None:
    update_project_settings(
        narrative_project.engine,
        narrative_project.project_id,
        {"voice": None, "speech_rate": None},
    )

    await invoke_tool(TTS_TOOL, _ctx(narrative_project), {"text": "a", "out_path": "a.mp3"})

    (request,) = tts_engine.requests
    assert (request.voice, request.speed) == (DEFAULT_VOICE, DEFAULT_SPEED)


async def test_explicit_speed_wins(
    narrative_project: NarrativeProjectEnv, tts_engine: _RecordingEngine
) -> None:
    await invoke_tool(
        TTS_TOOL, _ctx(narrative_project), {"text": "a", "out_path": "a.mp3", "speed": 0.9}
    )

    assert tts_engine.requests[0].speed == 0.9


@pytest.mark.parametrize(
    "out_path",
    [
        "../x.mp3",
        "/tmp/x.mp3",
        "uploads/a.mp3",
        ".cache/a.mp3",
        "upstream/a.mp3",
        "output/a.mp3",
        "a.txt",
        "a.wav",
        "dir/",
    ],
)
async def test_rejects_paths_it_must_not_write(
    narrative_project: NarrativeProjectEnv, tts_engine: _RecordingEngine, out_path: str
) -> None:
    before = sorted(p for p in Path(narrative_project.workdir).rglob("*") if p.is_file())

    result = await invoke_tool(
        TTS_TOOL, _ctx(narrative_project), {"text": "a", "out_path": out_path}
    )

    assert result.is_error
    assert tts_engine.requests == []
    after = sorted(p for p in Path(narrative_project.workdir).rglob("*") if p.is_file())
    assert after == before


@pytest.mark.parametrize("text", ["", "   "])
async def test_rejects_empty_text(
    narrative_project: NarrativeProjectEnv, tts_engine: _RecordingEngine, text: str
) -> None:
    result = await invoke_tool(
        TTS_TOOL, _ctx(narrative_project), {"text": text, "out_path": "a.mp3"}
    )

    assert result.is_error
    assert tts_engine.requests == []


async def test_reports_engine_failure_without_writing(
    narrative_project: NarrativeProjectEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda _voices: _RecordingEngine(fail=True))

    result = await invoke_tool(
        TTS_TOOL, _ctx(narrative_project), {"text": "a", "out_path": "a.mp3"}
    )

    assert result.is_error and "限流" in result.text
    assert not (narrative_project.workdir / "a.mp3").exists()
