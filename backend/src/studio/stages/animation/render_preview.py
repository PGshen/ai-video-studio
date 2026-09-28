"""`render_preview` 工具（设计 §5.3；计划 T8）：低清预览单个镜头。

从 `upstream/narrative/narrative.json`（镜头顺序）和
`upstream/narrative/timing.json`（每个镜头的音频路径/时长/beat 起止时刻）
拼出 T2 的 `PreviewRequest`：`0..scene_id` 对应位置（含）的每个镜头各一个
`SceneInput`，代码从 `animation/scenes/<id>.py` 读（缺失/为空的处理方式
与 `validate_scenes.py` 一致），音频用 `SceneAudio`，交给
`ManimRenderEngine.render_preview` 渲染。

**关键坑**：`timing.json` 里的 `audio_path` 字段（例如
`"narrative/audio/s-hook.wav"`）是叙事阶段自己工作区里的相对路径；物化到
`upstream/` 之后真正能读到的文件在 `upstream/<audio_path>`。`SceneAudio.
audio_path` 必须是绝对路径——`ManimRenderEngine` 把这个值原样嵌进生成的
manim 脚本源码里当字面量用，脚本是在一个临时目录（cwd）里跑子进程的，传
工作区相对路径会导致子进程 `add_sound()` 找不到文件。
"""

from __future__ import annotations

import base64
import json

from pydantic import BaseModel

from studio.agent.events import ImageData
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.engines.render.base import PreviewRequest, SceneAudio, SceneInput
from studio.engines.render.manim import ManimRenderEngine
from studio.workspace import files

_SCENES_DIR = "animation/scenes"
_NARRATIVE_PATH = "upstream/narrative/narrative.json"
_TIMING_PATH = "upstream/narrative/timing.json"


class RenderPreviewArgs(BaseModel):
    scene_id: str


def _scene_ids(ctx: ToolContext) -> list[str]:
    """按 `narrative.json` 里 `scenes[]` 的顺序返回镜头 id 列表。"""
    narrative_path = files.safe_path(ctx.workdir, _NARRATIVE_PATH)
    narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
    return [scene["id"] for scene in narrative["scenes"]]


def _timing_by_scene_id(ctx: ToolContext) -> dict[str, dict]:
    timing_path = files.safe_path(ctx.workdir, _TIMING_PATH)
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    return {scene["id"]: scene for scene in timing["scenes"]}


def _read_scene_code(ctx: ToolContext, scene_id: str) -> str:
    scene_path = files.safe_path(ctx.workdir, f"{_SCENES_DIR}/{scene_id}.py")
    return scene_path.read_text(encoding="utf-8") if scene_path.is_file() else ""


async def _handler(ctx: ToolContext, args: RenderPreviewArgs) -> ToolResult:
    scene_ids = _scene_ids(ctx)
    if args.scene_id not in scene_ids:
        return ToolResult(
            text=f"镜头 {args.scene_id} 不存在于当前叙事产物中。",
            is_error=True,
        )

    target_index = scene_ids.index(args.scene_id)
    timing_by_id = _timing_by_scene_id(ctx)

    missing: list[str] = []
    scenes: list[SceneInput] = []
    for index, scene_id in enumerate(scene_ids[: target_index + 1]):
        code = _read_scene_code(ctx, scene_id)
        if not code.strip():
            missing.append(scene_id)
            continue

        scene_timing = timing_by_id[scene_id]
        # timing.json 里的 audio_path 是相对 upstream/ 的相对路径；SceneAudio
        # 需要绝对路径（见模块 docstring）。
        audio_path = files.safe_path(ctx.workdir, f"upstream/{scene_timing['audio_path']}")
        scenes.append(
            SceneInput(
                scene_index=index,
                narration="",
                description=scene_id,
                code=code,
                audio=SceneAudio(
                    scene_index=index,
                    audio_path=str(audio_path),
                    duration_seconds=scene_timing["duration_seconds"],
                ),
            )
        )

    if missing:
        return ToolResult(
            text="以下镜头缺少代码或代码为空，需要先写好再预览：" + "、".join(missing),
            is_error=True,
        )

    target_timing = timing_by_id[args.scene_id]
    audio_duration_seconds = target_timing["duration_seconds"]
    request = PreviewRequest(
        scenes=scenes,
        target_scene_index=target_index,
        beat_end_times=[beat["end_seconds"] for beat in target_timing["beats"]],
        audio_duration_seconds=audio_duration_seconds,
    )

    result = await ManimRenderEngine().render_preview(request)
    if not result.success:
        return ToolResult(text=result.error_message or "预览渲染失败。", is_error=True)

    images = [
        ImageData(
            media_type="image/png",
            data_base64=base64.b64encode(keyframe.png_bytes).decode("ascii"),
        )
        for keyframe in result.keyframes
    ]
    deviation_text = (
        f"{result.duration_deviation_seconds:.2f}s"
        if result.duration_deviation_seconds is not None
        else "未知"
    )
    render_duration_text = (
        f"{result.render_duration_seconds:.2f}s"
        if result.render_duration_seconds is not None
        else "未知"
    )
    text = (
        f"镜头 {args.scene_id} 预览渲染完成：渲染时长 {render_duration_text}，"
        f"配音时长 {audio_duration_seconds:.2f}s，偏差 {deviation_text}。"
    )
    return ToolResult(text=text, images=images)


RENDER_PREVIEW_TOOL = ToolSpec(
    name="render_preview",
    description="低清预览单个镜头，返回关键帧图片与渲染/配音时长偏差。",
    input_model=RenderPreviewArgs,
    stages={"animation"},
    handler=_handler,
)
