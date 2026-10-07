"""Real-model smoke for the music video (imported song) pipeline (4B T10). Run with `make smoke`.

`concept → produce` with a real song (uploaded and analysed in `concept`) and the local Claude
login, then a real Chromium + ffmpeg final render. The song is the owner's file, never committed:
it comes from
`STUDIO_SMOKE_SONG` (the `make smoke` whitelist passes `STUDIO_*` variables) or defaults to
`docs/temp/海阔天空.mp3`; the case skips when the file is missing.

The agent cannot hear: the downbeat phase, the sections and the fades are judged by the owner's
ears afterwards. This case asserts structure (artifacts, durations, audio track, `final.json`) and
records the fit readings, render time and file size as evidence.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from studio.agent.stage_flow import finalize
from studio.engines.audio.probe import probe_audio
from studio.timeline.lyrics import parse_lrc

from .support import (
    IMPORT_MUSIC_EVIDENCE_DIR,
    REPO_ROOT,
    build_harness,
    outcome_summary,
    record_evidence,
)
from .test_smoke import _last_ok, _skip_unless_claude_login

pytestmark = pytest.mark.smoke

DEFAULT_SONG = REPO_ROOT / "docs" / "temp" / "海阔天空.mp3"

_CONCEPT_PROMPT = (
    "我们要给工作区里的这首歌（music/source.mp3，已上传）做一支没有旁白的音乐 MV。"
    "先调用 analyze_music 看歌的 BPM、总长和能量曲线；工作区里还有用户上传的歌词 "
    "music/lyrics.lrc，先读它，再按提示词写出 concept/brief.md：情绪走向、视觉母题、"
    "歌词意象（逐句写歌词原句 → 画面）、段落草图；目标时长按整首歌，"
    "硬性要求写“只用黑白灰加一种强调色”。写完用 check_concept 检查并修好。不需要联网查资料。"
)
_PRODUCE_PROMPT = (
    "按创意简报为这首歌做画面：先看分析图（需要时调用 analyze_music），不截取（用整首歌），"
    "按歌的结构和歌词乐句写 animation/shots.json 和每个镜头的场景脚本，画面按简报的歌词意象"
    "用 env.lyric() 跟着歌词走，并对齐 beat/downbeat 事件与 env.energy。"
    "按镜头顺序逐个做：写完先用 validate_scenes_html 校验该镜头，再用 render_preview_html 看图；"
    "全部做完后做一次全量校验。最后说明你靠什么判断、哪些东西无法验证。"
)
# Self-written placeholder lines (not the song's lyrics), used when `STUDIO_SMOKE_LRC` is unset:
# they exercise the mechanism (brief chapter, `env.lyric`, preview samples), not the owner's taste.
_PLACEHOLDER_LINES = [
    (12.0, "凌晨三点 机房亮着光"),
    (30.0, "一个小点 开始发烫"),
    (55.0, "曲线向上 撞穿屋顶"),
    (80.0, "数字滚动 没有尽头"),
    (110.0, "它问我 你还在吗"),
    (140.0, "小数点 又挪了一位"),
    (170.0, "世界折成 回形针"),
    (200.0, "我伸手 去够电源"),
    (230.0, "注意力 一层一层"),
    (260.0, "光 越来越亮"),
    (290.0, "天亮之前 它还醒着"),
]
_FOLLOW_UP = "上一轮的最终结果还有错误。根据工具返回的错误继续修复，直到全部通过。"


def _lyrics(duration: float) -> str:
    """The owner's LRC (`STUDIO_SMOKE_LRC`) or the placeholder lines that fit the song."""
    path = os.environ.get("STUDIO_SMOKE_LRC")
    if path:
        return Path(path).read_text(encoding="utf-8")
    return "\n".join(
        f"[{int(t) // 60:02d}:{t % 60:05.2f}]{text}"
        for t, text in _PLACEHOLDER_LINES
        if t < duration - 5
    )


def _song() -> Path:
    song = Path(os.environ.get("STUDIO_SMOKE_SONG") or DEFAULT_SONG)
    if not song.is_file():
        pytest.skip(f"没有找到歌曲文件 {song}（设置 STUDIO_SMOKE_SONG 或放到 docs/temp/），跳过")
    return song


async def test_music_video_claude_login(tmp_path: Path) -> None:
    from studio.engines.render.html.pool import close_browser_pool

    song = _song()
    _skip_unless_claude_login()
    harness = build_harness(tmp_path, real_stages=True, music_video=True)
    evidence: dict[str, Any] = {"song": song.name, "stages": {}}
    stage_plan = [
        ("concept", _CONCEPT_PROMPT, ("check_concept", "analyze_music"), 60),
        ("produce", _PRODUCE_PROMPT, ("validate_scenes_html",), 160),
    ]
    try:
        work = harness.workdir
        # What the upload endpoint does (validated by tests/api/test_music_upload.py): the song
        # lands as `music/source.<ext>` after an ffprobe check.
        probe = await probe_audio(song)
        evidence["probe"] = {"duration": probe.duration, "codec": probe.codec}
        (work / "music").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(song, work / "music" / f"source{song.suffix.lower()}")
        lrc = _lyrics(probe.duration)
        (work / "music" / "lyrics.lrc").write_text(lrc, encoding="utf-8")
        evidence["lyrics"] = {
            "source": "STUDIO_SMOKE_LRC" if os.environ.get("STUDIO_SMOKE_LRC") else "placeholder",
            "lines": len(parse_lrc(lrc, probe.duration)),
        }

        for stage, prompt, tools, steps in stage_plan:
            profile = harness.profile("claude-login", max_steps_per_turn=steps, suffix=f"-{stage}")
            session = harness.session(profile, "claude", stage=stage)
            turns = [await harness.turn(session, prompt)]
            if any(_last_ok(turns, tool) is None for tool in tools):
                turns.append(await harness.turn(session, _FOLLOW_UP))
            assert all(t.turn.status == "done" for t in turns), [
                (t.turn.status, t.turn.error) for t in turns
            ]
            finals = {tool: _last_ok(turns, tool) for tool in tools}
            for tool, final in finals.items():
                assert final is not None, f"{stage}：最后一次 {tool} 没有成功"
            evidence["stages"][stage] = {
                "turns": [outcome_summary(t) for t in turns],
                "tool_calls": [name for t in turns for name in t.tool_names],
                "final_text": {
                    tool: final["text"][:2000] for tool, final in finals.items() if final
                },
            }
            blockers = harness.registry.get(stage).finalize_blockers(work)
            assert blockers == [], (stage, blockers)
            finalize(harness.engine, harness.blobs, harness.registry, harness.project_id, stage)
            if stage == "concept":
                evidence["analysis"] = _analysis_readings(work)

        shots = json.loads((work / "animation" / "shots.json").read_text("utf-8"))
        evidence["shots"] = shots
        for shot in shots["shots"]:
            assert (work / "animation" / "scenes" / f"{shot['id']}.js").is_file(), shot
        scenes = "".join(
            (work / "animation" / "scenes" / f"{shot['id']}.js").read_text("utf-8")
            for shot in shots["shots"]
        )
        assert "env.lyric" in scenes, "没有任何场景脚本引用 env.lyric / env.lyrics"
        evidence["brief_has_imagery"] = "歌词意象" in (work / "concept" / "brief.md").read_text(
            "utf-8"
        )
        calls = evidence["stages"]["produce"]["tool_calls"]
        assert "render_preview_html" in calls, "没有调用 render_preview_html"
        evidence["final"] = await _render_final(harness)
    finally:
        record_evidence("music-video-claude-login", evidence, IMPORT_MUSIC_EVIDENCE_DIR)
        await close_browser_pool()
        harness.engine.dispose()


def _analysis_readings(work: Path) -> dict[str, Any]:
    """The fit readings the owner compares with what they hear (phase, bpm, confidence)."""
    analysis = json.loads((work / "music" / "analysis.json").read_text("utf-8"))
    return {
        "bpm": analysis["bpm"],
        "offset": analysis["offset"],
        "confidence": analysis["confidence"],
        "residual_ms": analysis["residual_ms"],
        "duration": analysis["duration"],
        "warnings": analysis["warnings"],
        "candidates": analysis["candidates"],
    }


async def _render_final(harness: Any) -> dict[str, Any]:
    """Real Chromium + ffmpeg: the audio track is the song's range, the length is the timeline's."""
    from studio.jobs import create_job, get_job
    from studio.timeline.load import TimelineSources, load_timeline
    from studio.worker import run_once

    expected = load_timeline(
        TimelineSources(harness.workdir, narration=False, music_source="import", produce=True)
    ).timeline.duration
    job = create_job(harness.engine, type="final_render", project_id=harness.project_id, payload={})
    started = time.monotonic()
    assert await run_once(harness.engine, harness.blobs, data_dir=harness.data_dir) is True
    done = get_job(harness.engine, job.id)
    assert done is not None and done.status == "done", done.error if done else None
    seconds = round(time.monotonic() - started, 1)
    final = harness.workdir / "output" / "final.mp4"
    probe = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(final)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    audio = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    duration = float(probe["format"]["duration"])
    assert len(audio) == 1, audio
    assert abs(duration - expected) <= 0.15, (duration, expected)
    meta = json.loads((harness.workdir / "output" / "final.json").read_text("utf-8"))
    assert set(meta["audio_sources"]) == {"music"} and "music_hash" not in meta
    return {
        "seconds": seconds,
        "duration": duration,
        "expected": expected,
        "bytes": final.stat().st_size,
        "audio_codec": audio[0]["codec_name"],
        "range": meta["audio_sources"]["music"]["range"],
        "kept_for_listening": str(_keep(final)),
    }


def _keep(final: Path) -> Path:
    """Copy the film next to the evidence so the owner can listen after the temp dir is gone."""
    IMPORT_MUSIC_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    target = IMPORT_MUSIC_EVIDENCE_DIR / "music-video-final.mp4"
    shutil.copyfile(final, target)
    return target
