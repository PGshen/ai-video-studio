"""时间轴构建（设计 §4.2）：本阶段只实现旁白层。

读文件由调用方负责；这里的函数只处理已解析的 dict 和数据结构。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from studio.timeline.schema import Beat, NarrationScene, Section, Timeline

_TOLERANCE = 0.05
"""beat 起止允许超出镜头时长的容差（秒），与配音对齐的取整误差同量级。"""


class LayerNotSupported(ValueError):
    """传入了本阶段尚未实现的层（网格、时刻、配乐）。"""


class TimelineError(ValueError):
    def __init__(self, errors: list[str] | tuple[str, ...]):
        self.errors = tuple(errors)
        details = "\n".join(f"- {error}" for error in self.errors)
        super().__init__(f"时间轴不可用，共 {len(self.errors)} 个问题：\n{details}")


@dataclass(frozen=True, slots=True)
class NarrationInput:
    scene_id: str
    label: str
    duration_seconds: float
    beats: list[tuple[float, float, str]]
    """`(start, end, cue_text)`，起止是镜头内的相对秒。"""


@dataclass(frozen=True, slots=True)
class TimelineLayers:
    narration: list[NarrationInput]
    grid: Any = None
    moments: Any = None
    music: Any = None


def build_timeline(layers: TimelineLayers) -> Timeline:
    for name in ("grid", "moments", "music"):
        if getattr(layers, name) is not None:
            raise LayerNotSupported(f"时间轴的 {name} 层尚未实现")
    if not layers.narration:
        raise TimelineError(["没有任何镜头"])

    sections: list[Section] = []
    narration: list[NarrationScene] = []
    cursor = 0.0
    for scene in layers.narration:
        end = cursor + scene.duration_seconds
        sections.append(Section(id=scene.scene_id, label=scene.label, start=cursor, end=end))
        narration.append(
            NarrationScene(
                scene_id=scene.scene_id,
                start=cursor,
                end=end,
                beats=[
                    Beat(start=cursor + start, end=cursor + stop, cue_text=text)
                    for start, stop, text in scene.beats
                ],
            )
        )
        cursor = end
    return Timeline(duration=cursor, sections=sections, narration=narration)


def _label_of(scene: dict[str, Any], scene_id: str) -> str:
    intent = scene.get("visual_intent")
    if not isinstance(intent, str) or not intent.strip():
        return scene_id
    first = intent.strip().split("。")[0].strip()
    return first or scene_id


def narration_from_documents(
    narrative_doc: dict[str, Any], timing_doc: dict[str, Any]
) -> list[NarrationInput]:
    """合并 `narrative.json` 与 `timing.json`；问题一次性汇总成 `TimelineError`。"""
    errors: list[str] = []
    raw_scenes = narrative_doc.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise TimelineError(["narrative.json 里没有任何镜头"])
    timing_by_id = {
        scene.get("id"): scene for scene in timing_doc.get("scenes", []) if isinstance(scene, dict)
    }

    result: list[NarrationInput] = []
    seen: set[str] = set()
    for index, scene in enumerate(raw_scenes):
        scene_id = scene.get("id") if isinstance(scene, dict) else None
        if not isinstance(scene_id, str) or not scene_id:
            errors.append(f"第 {index} 个镜头缺少 id")
            continue
        if scene_id in seen:
            errors.append(f"镜头 id {scene_id} 重复")
            continue
        seen.add(scene_id)

        timing = timing_by_id.get(scene_id)
        if timing is None:
            errors.append(f"镜头 {scene_id}：timing.json 缺少对应记录")
            continue
        duration = timing.get("duration_seconds")
        if not isinstance(duration, int | float) or duration <= 0:
            errors.append(f"镜头 {scene_id}：配音时长必须为正数（当前 {duration!r}）")
            continue

        cues = [beat.get("cue_text", "") for beat in scene.get("beats", [])]
        spans = timing.get("beats", [])
        if len(cues) != len(spans):
            errors.append(
                f"镜头 {scene_id}：beat 数不一致（叙事 {len(cues)} 个，timing {len(spans)} 个）"
            )
            continue

        beats: list[tuple[float, float, str]] = []
        scene_ok = True
        for beat_index, (cue, span) in enumerate(zip(cues, spans, strict=True)):
            start, end = float(span["start_seconds"]), float(span["end_seconds"])
            if end < start:
                errors.append(f"镜头 {scene_id}：第 {beat_index} 个 beat 起止倒置（{start}→{end}）")
                scene_ok = False
            elif start < -_TOLERANCE or end > duration + _TOLERANCE:
                errors.append(
                    f"镜头 {scene_id}：第 {beat_index} 个 beat 超出镜头时长 {duration}s"
                    f"（{start}→{end}）"
                )
                scene_ok = False
            beats.append((start, end, cue))
        if scene_ok:
            label = _label_of(scene, scene_id)
            result.append(NarrationInput(scene_id, label, float(duration), beats))

    if errors:
        raise TimelineError(errors)
    return result


def _round_floats(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return [_round_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}
    return value


def timeline_hash(timeline: Timeline) -> str:
    canonical = json.dumps(
        _round_floats(timeline.model_dump(mode="json")),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
