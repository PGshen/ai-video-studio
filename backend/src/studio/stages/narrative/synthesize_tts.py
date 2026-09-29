"""`synthesize_tts` 工具（设计 §5.2；计划 M3 T6）：对镜头配音并对齐 beat。

`_ENGINE_FACTORY` 是模块级的可替换"缝"：默认是真实的
`engines.tts.factory.build_tts_engine`，测试用 `monkeypatch.setattr` 换成
假引擎，不需要改 `ToolContext`/`ToolSpec` 的签名。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.db.repo.projects import get_project
from studio.engines.tts import TTSEngine, TTSRequest, align_scene_beats, build_tts_engine
from studio.stages.narrative.schema import NarrativeValidationError, validate_and_normalize
from studio.workspace import files

_NARRATIVE_PATH = "narrative/narrative.json"
_TIMING_PATH = "narrative/timing.json"
_DEFAULT_VOICE = "zizi"
_DEFAULT_SPEED = 1.0

_ENGINE_FACTORY: Callable[[], TTSEngine] = build_tts_engine


class SynthesizeTtsArgs(BaseModel):
    scene_ids: list[str] | None = None


def _read_narrative(ctx: ToolContext) -> tuple[Any, list[str]]:
    narrative_path = files.safe_path(ctx.workdir, _NARRATIVE_PATH)
    if not narrative_path.is_file():
        return None, ["还没有写 narrative/narrative.json。"]
    try:
        raw = json.loads(narrative_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"narrative.json 不是合法的 JSON：{exc}"]
    try:
        narrative = validate_and_normalize(raw)
    except NarrativeValidationError as exc:
        return None, list(exc.errors)
    return narrative, []


def _read_timing_doc(ctx: ToolContext) -> dict[str, Any]:
    timing_path = files.safe_path(ctx.workdir, _TIMING_PATH)
    if not timing_path.is_file():
        return {"scenes": []}
    return json.loads(timing_path.read_text(encoding="utf-8"))


def _write_bytes(ctx: ToolContext, relpath: str, data: bytes) -> None:
    path = files.safe_path(ctx.workdir, relpath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    ctx.record_tool_write(relpath, hashlib.sha256(data).hexdigest())


def _write_text(ctx: ToolContext, relpath: str, text: str) -> None:
    path = files.safe_path(ctx.workdir, relpath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    ctx.record_tool_write(relpath, hashlib.sha256(text.encode("utf-8")).hexdigest())


def _project_voice_and_speed(ctx: ToolContext) -> tuple[str, float]:
    project = get_project(ctx.engine, ctx.project_id) if ctx.engine is not None else None
    settings = project.settings if project is not None else {}
    return (
        settings.get("voice", _DEFAULT_VOICE),
        settings.get("speech_rate", _DEFAULT_SPEED),
    )


async def _handler(ctx: ToolContext, args: SynthesizeTtsArgs) -> ToolResult:
    narrative, errors = _read_narrative(ctx)
    if narrative is None:
        return ToolResult(text="\n".join(errors), is_error=True)

    scenes_by_id = {scene.id: scene for scene in narrative.scenes}
    if args.scene_ids is None:
        target_ids = list(scenes_by_id)
    else:
        missing = [sid for sid in args.scene_ids if sid not in scenes_by_id]
        if missing:
            return ToolResult(
                text="以下镜头 id 不存在于当前叙事产物中：" + "、".join(missing),
                is_error=True,
            )
        target_ids = list(args.scene_ids)

    voice, speed = _project_voice_and_speed(ctx)
    engine = _ENGINE_FACTORY()

    timing_doc = _read_timing_doc(ctx)
    timing_by_id = {scene["id"]: scene for scene in timing_doc.get("scenes", [])}

    succeeded: list[str] = []
    failed: list[str] = []
    for scene_id in target_ids:
        scene = scenes_by_id[scene_id]
        result = await engine.synthesize(TTSRequest(text=scene.narration, voice=voice, speed=speed))
        if not result.success:
            failed.append(f"{scene_id}（{result.error_message or '未知错误'}）")
            continue

        audio_relpath = f"narrative/audio/{scene_id}.mp3"
        _write_bytes(ctx, audio_relpath, result.audio_bytes)
        audio_sha256 = hashlib.sha256(result.audio_bytes).hexdigest()

        aligned = align_scene_beats(
            {
                "narration": scene.narration,
                "duration_seconds": result.duration_seconds,
                "beats": [{"cue_text": beat.cue_text} for beat in scene.beats],
                "word_timestamps": [
                    {"word": w.word, "start_time": w.start_time, "end_time": w.end_time}
                    for w in result.word_timestamps
                ],
            },
            scene_id=scene_id,
        )

        timing_by_id[scene_id] = {
            "id": scene_id,
            "audio_path": audio_relpath,
            "audio_hash": f"sha256:{audio_sha256}",
            "duration_seconds": result.duration_seconds,
            "beats": [
                {
                    "start_seconds": beat["speech_start_seconds"],
                    "end_seconds": beat["speech_end_seconds"],
                }
                for beat in aligned["beats"]
            ],
            "word_timestamps": [
                {"word": item.word, "start_seconds": item.start_time, "end_seconds": item.end_time}
                for item in result.word_timestamps
            ],
            "alignment_coverage": aligned["alignment_coverage"],
        }
        succeeded.append(
            f"{scene_id}（时长 {result.duration_seconds:.2f}s，"
            f"对齐覆盖率 {aligned['alignment_coverage']:.0%}）"
        )

    if succeeded:
        # Narrative order first; entries for scenes no longer in narrative.json are kept as-is.
        ordered_ids = [sid for sid in scenes_by_id if sid in timing_by_id]
        ordered_ids += [sid for sid in timing_by_id if sid not in scenes_by_id]
        new_timing_doc = {"scenes": [timing_by_id[sid] for sid in ordered_ids]}
        _write_text(ctx, _TIMING_PATH, json.dumps(new_timing_doc, ensure_ascii=False, indent=2))

    lines: list[str] = []
    if succeeded:
        lines.append("已配音：" + "、".join(succeeded))
    if failed:
        lines.append("配音失败：" + "、".join(failed))
    return ToolResult(text="\n".join(lines) or "没有镜头需要配音。", is_error=bool(failed))


SYNTHESIZE_TTS_TOOL = ToolSpec(
    name="synthesize_tts",
    description=(
        "对指定镜头（或全部）配音并对齐 beat，写 narrative/audio/*.mp3 和 narrative/timing.json。"
    ),
    input_model=SynthesizeTtsArgs,
    stages={"narrative"},
    handler=_handler,
)
