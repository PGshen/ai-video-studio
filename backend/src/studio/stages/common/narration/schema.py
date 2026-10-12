"""叙事产物 schema（设计 §5.2；计划 M3 T3）。

`validate_and_normalize` 一次性收集全部错误再报出（不是遇到第一个就
停），供 `validate_narrative` 工具（T4）和 `synthesize_tts` 工具（T5）
共用。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from studio.engines.tts.text_normalize import normalize_alignment_text


class Beat(BaseModel):
    cue_text: str
    visual_action: str
    emphasis: str
    transition: Literal["continue", "transform", "reveal", "replace", "exit"]


class Scene(BaseModel):
    id: str
    narration: str
    visual_intent: str
    beats: list[Beat]


class Narrative(BaseModel):
    scenes: list[Scene]


class NarrativeValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = tuple(errors)
        details = "\n".join(f"- {error}" for error in errors)
        super().__init__(f"叙事产物校验失败，共 {len(errors)} 个问题：\n{details}")


def _pydantic_errors_for_scene(scene_label: str, raw_scene: dict[str, Any]) -> list[str]:
    try:
        Scene.model_validate(raw_scene)
    except ValidationError as exc:
        messages: list[str] = []
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"])
            messages.append(f"镜头 {scene_label} 字段 {field or '(顶层)'}: {error['msg']}")
        return messages
    return []


def validate_and_normalize(raw: dict[str, Any]) -> Narrative:
    """校验并解析 `narrative.json` 的原始 dict；有任何问题就抛
    `NarrativeValidationError(errors)`，不返回部分结果。
    """
    errors: list[str] = []
    raw_scenes = raw.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise NarrativeValidationError(["scenes 不能为空"])

    seen_ids: set[str] = set()
    for index, raw_scene in enumerate(raw_scenes):
        if not isinstance(raw_scene, dict):
            errors.append(f"第 {index} 个镜头必须是对象")
            continue
        scene_id = raw_scene.get("id")
        label = scene_id if isinstance(scene_id, str) and scene_id else f"#{index}"

        if not isinstance(scene_id, str) or not scene_id:
            errors.append(f"镜头 {label} 缺少非空的 id")
        elif scene_id in seen_ids:
            errors.append(f"镜头 id {scene_id} 重复")
        else:
            seen_ids.add(scene_id)

        errors.extend(_pydantic_errors_for_scene(label, raw_scene))

        narration = raw_scene.get("narration")
        beats = raw_scene.get("beats")
        if isinstance(beats, list) and not beats:
            errors.append(f"镜头 {label} 的 beats 不能为空")
        if isinstance(narration, str) and isinstance(beats, list) and beats:
            cue_texts: list[str] = []
            all_cues_are_strings = True
            for beat in beats:
                cue = beat.get("cue_text") if isinstance(beat, dict) else None
                if not isinstance(cue, str):
                    all_cues_are_strings = False
                    break
                cue_texts.append(cue)
            if all_cues_are_strings:
                joined = normalize_alignment_text("".join(cue_texts))
                if joined != normalize_alignment_text(narration):
                    errors.append(f"镜头 {label} 的 beats.cue_text 未完整覆盖 narration")

    if errors:
        raise NarrativeValidationError(errors)

    return Narrative.model_validate(raw)
