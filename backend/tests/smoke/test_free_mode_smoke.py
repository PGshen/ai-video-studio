"""Real-model smoke for free mode (free-mode plan T10). Run with `make smoke SMOKE_ARGS="-k free"`.

One stage does everything, with the local Claude login: a free explainer from a bare topic (the
first turn should propose and ask, not build), a free reel from one sentence, and a free MV that
reaches a passing scene check. Films are rendered with real Chromium + ffmpeg.

Voice is a stand-in that writes silent WAV with per-character timestamps: real TTS costs money and
is not what this case checks (the agent's behaviour in the free stage is). The real synthesis is
covered by the Volcengine cases in `test_smoke.py`.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import time
import wave
from pathlib import Path
from typing import Any

import pytest

from studio.engines.tts import TTSRequest, TTSResult, WordTimestamp
from studio.stages.common.narration import synthesize_tts as synthesize_tts_module
from studio.stages.pipeline import ProjectKind

from .support import REPO_ROOT, build_harness, outcome_summary, record_evidence
from .test_smoke import _last_ok, _skip_unless_claude_login

pytestmark = pytest.mark.smoke

FREE_EVIDENCE_DIR = REPO_ROOT / "data" / "evidence" / "free-mode" / "smoke"
DEFAULT_SONG = REPO_ROOT / "docs" / "temp" / "海阔天空.mp3"
_SECONDS_PER_CHAR = 0.2
_RATE = 16000

_EXPLAINER_ASK = "做一条讲「为什么天空是蓝色的」的讲解视频。"
_EXPLAINER_GO = (
    "按这个做：60 秒以内，3 个镜头左右，面向中学生，不要背景乐。直接做完：写叙事并用 "
    "validate_narrative 校验、synthesize_tts 配音，再逐个镜头写场景，用 validate_scenes_html 校验、"
    "render_preview_html 看图，最后做一次全量校验。"
)
_REEL_GO = (
    "直接做，不用先问我：一支 20 秒左右的无旁白动态图形短片，主题是「心跳」，"
    "合成一段 100 BPM 左右的配乐（写 music/compose.py 并用 render_music 渲染），按配乐写 "
    "animation/shots.json 和每个镜头的场景，用 validate_scenes_html 校验、"
    "render_preview_html 看图，最后做一次全量校验。"
)
_MV_GO = (
    "直接做，不用先问我：给这首已上传的歌（music/source.mp3）做 MV 画面，只截取开头 30 秒"
    "（写 music/range.json）。先 analyze_music 看图，再写 animation/shots.json 和每个镜头的场景，"
    "画面黑白灰加一种强调色、跟着 beat 走。用 validate_scenes_html 校验，最后做一次全量校验。"
)
_FOLLOW_UP = "上一轮的最终结果还有错误。根据工具返回的错误继续修复，直到全部通过。"


def _silent_wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(_RATE)
        out.writeframes(b"\x00\x00" * int(_RATE * seconds))
    return buffer.getvalue()


class _SilentTTSEngine:
    """Silent WAV, one timestamp per character: alignment and rendering work, no paid call."""

    engine_name = "silent"

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        seconds = round(len(request.text) * _SECONDS_PER_CHAR, 3)
        return TTSResult(
            success=True,
            output_path=None,
            duration_seconds=seconds,
            error_message=None,
            audio_bytes=_silent_wav(seconds),
            word_timestamps=[
                WordTimestamp(
                    word=char,
                    start_time=round(i * _SECONDS_PER_CHAR, 3),
                    end_time=round((i + 1) * _SECONDS_PER_CHAR, 3),
                )
                for i, char in enumerate(request.text)
            ],
        )

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def silent_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        synthesize_tts_module, "_ENGINE_FACTORY", lambda _voices: _SilentTTSEngine()
    )


async def _run(harness: Any, stage: str, prompts: list[str], tools: tuple[str, ...]) -> list[Any]:
    profile = harness.profile("claude-login", max_steps_per_turn=160, suffix=f"-{stage}")
    session = harness.session(profile, "claude", stage=stage)
    turns = [await harness.turn(session, prompt) for prompt in prompts]
    if any(_last_ok(turns, tool) is None for tool in tools):
        turns.append(await harness.turn(session, _FOLLOW_UP))
    assert all(t.turn.status == "done" for t in turns), [
        (t.turn.status, t.turn.error) for t in turns
    ]
    for tool in tools:
        assert _last_ok(turns, tool) is not None, f"最后一次 {tool} 没有成功"
    return turns


async def _render_final(harness: Any, name: str) -> dict[str, Any]:
    from studio.jobs import create_job, get_job
    from studio.worker import run_once

    job = create_job(harness.engine, type="final_render", project_id=harness.project_id, payload={})
    started = time.monotonic()
    assert await run_once(harness.engine, harness.blobs, data_dir=harness.data_dir) is True
    done = get_job(harness.engine, job.id)
    assert done is not None and done.status == "done", done.error if done else None
    final = harness.workdir / "output" / "final.mp4"
    probe = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(final)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    FREE_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    kept = FREE_EVIDENCE_DIR / f"{name}.mp4"
    shutil.copyfile(final, kept)
    return {
        "seconds": round(time.monotonic() - started, 1),
        "duration": float(probe["format"]["duration"]),
        "bytes": final.stat().st_size,
        "kept": str(kept),
    }


async def test_free_explainer_claude_login(tmp_path: Path, silent_voice: None) -> None:
    from studio.engines.render.html.pool import close_browser_pool

    _skip_unless_claude_login()
    harness = build_harness(
        tmp_path, real_stages=True, free=ProjectKind("html", True, "none", "free")
    )
    evidence: dict[str, Any] = {}
    try:
        profile = harness.profile("claude-login", max_steps_per_turn=40, suffix="-ask")
        session = harness.session(profile, "claude", stage="free_explainer")
        first = await harness.turn(session, _EXPLAINER_ASK)
        evidence["first_turn"] = outcome_summary(first)
        assert first.turn.status == "done", first.turn.error
        scenes_dir = harness.workdir / "animation" / "scenes"
        assert not scenes_dir.exists() or not any(scenes_dir.glob("*.js")), "第一轮就写了场景"
        assert not (harness.workdir / "narrative" / "timing.json").exists(), "第一轮就配了音"
        reply = first.text
        assert "？" in reply or "?" in reply, reply

        turns = await _run(
            harness,
            "free_explainer",
            [_EXPLAINER_GO],
            ("validate_narrative", "synthesize_tts", "validate_scenes_html"),
        )
        evidence["build_turns"] = [outcome_summary(t) for t in turns]
        evidence["tool_calls"] = [name for t in turns for name in t.tool_names]
        evidence["final"] = await _render_final(harness, "free-explainer")
    finally:
        record_evidence("free-explainer-claude-login", evidence, FREE_EVIDENCE_DIR)
        await close_browser_pool()
        harness.engine.dispose()


async def test_free_reel_claude_login(tmp_path: Path) -> None:
    from studio.engines.render.html.pool import close_browser_pool

    _skip_unless_claude_login()
    harness = build_harness(
        tmp_path, real_stages=True, free=ProjectKind("html", False, "synth", "free")
    )
    evidence: dict[str, Any] = {}
    try:
        turns = await _run(
            harness, "free_produce", [_REEL_GO], ("render_music", "validate_scenes_html")
        )
        evidence["turns"] = [outcome_summary(t) for t in turns]
        evidence["tool_calls"] = [name for t in turns for name in t.tool_names]
        assert harness.registry.get("free_produce").finalize_blockers(harness.workdir) == []
        evidence["final"] = await _render_final(harness, "free-reel")
    finally:
        record_evidence("free-reel-claude-login", evidence, FREE_EVIDENCE_DIR)
        await close_browser_pool()
        harness.engine.dispose()


async def test_free_mv_claude_login(tmp_path: Path) -> None:
    from studio.engines.render.html.pool import close_browser_pool

    song = Path(os.environ.get("STUDIO_SMOKE_SONG") or DEFAULT_SONG)
    if not song.is_file():
        pytest.skip(f"没有找到歌曲文件 {song}（设置 STUDIO_SMOKE_SONG 或放到 docs/temp/），跳过")
    _skip_unless_claude_login()
    harness = build_harness(
        tmp_path, real_stages=True, free=ProjectKind("html", False, "import", "free")
    )
    evidence: dict[str, Any] = {"song": song.name}
    try:
        (harness.workdir / "music").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(song, harness.workdir / "music" / f"source{song.suffix.lower()}")
        turns = await _run(
            harness, "free_produce", [_MV_GO], ("analyze_music", "validate_scenes_html")
        )
        evidence["turns"] = [outcome_summary(t) for t in turns]
        evidence["tool_calls"] = [name for t in turns for name in t.tool_names]
        assert harness.registry.get("free_produce").finalize_blockers(harness.workdir) == []
    finally:
        record_evidence("free-mv-claude-login", evidence, FREE_EVIDENCE_DIR)
        await close_browser_pool()
        harness.engine.dispose()
