"""时间轴构建（设计 §4.2；子项目 3 设计 §4.1）：旁白层，加网格、节拍脚本点与配乐三层。

读文件由调用方负责；这里的函数只处理已解析的 dict 和数据结构。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from studio.timeline.notation import parse_at
from studio.timeline.schema import (
    Beat,
    Energy,
    Grid,
    Moment,
    Music,
    MusicEvent,
    NarrationScene,
    Section,
    Timeline,
)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
"""镜头 id 会变成文件名、URL 路径和 JS 字符串键，只允许字母、数字、下划线和连字符。"""
_TOLERANCE = 0.05
"""beat 起止允许超出镜头时长的容差（秒），与配音对齐的取整误差同量级。"""


class LayerNotSupported(ValueError):
    """传入了尚未实现的层（歌词）。"""


_MAX_SHOWN_ERRORS = 20  # the message ends up in one tool result (SDK limit: 1 MiB)


class TimelineError(ValueError):
    def __init__(self, errors: list[str] | tuple[str, ...]):
        self.errors = tuple(errors)
        shown = [e if len(e) <= 300 else e[:300] + "…" for e in self.errors[:_MAX_SHOWN_ERRORS]]
        if len(self.errors) > _MAX_SHOWN_ERRORS:
            shown.append(f"……还有 {len(self.errors) - _MAX_SHOWN_ERRORS} 个问题未列出")
        details = "\n".join(f"- {error}" for error in shown)
        super().__init__(f"时间轴不可用，共 {len(self.errors)} 个问题：\n{details}")


MUSIC_FILE = "music/music.wav"
BPM_RANGE = (40.0, 240.0)
EVENT_KINDS = ("onset", "sweep")
_BEATS_PER_BAR = 4
_DURATION_TOLERANCE = 0.05


def _finite(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


_BPM_TOLERANCE = 0.01
_EPSILON = 1e-6


@dataclass(frozen=True, slots=True)
class NarrationInput:
    scene_id: str
    label: str
    duration_seconds: float
    beats: list[tuple[float, float, str]]
    """`(start, end, cue_text)`，起止是镜头内的相对秒。"""


@dataclass(frozen=True, slots=True)
class GridInput:
    bpm: float
    offset: float = 0.0


@dataclass(frozen=True, slots=True)
class SectionInput:
    """短片的段落：时长由小节数和 BPM 推出。"""

    id: str
    label: str
    bars: int


@dataclass(frozen=True, slots=True)
class MomentInput:
    section_id: str
    at: str
    """小节.拍记法，相对本段，从 1 开始。"""
    visual_action: str


@dataclass(frozen=True, slots=True)
class MusicInput:
    events: list[dict[str, Any]]
    energy_hop: float
    energy_values: list[float]
    declared_duration: float | None = None
    declared_bpm: float | None = None
    """短片里与节拍脚本核对；有旁白的项目网格本身取自它，不再核对。"""


@dataclass(frozen=True, slots=True)
class TimelineLayers:
    narration: list[NarrationInput]
    grid: GridInput | None = None
    moments: list[MomentInput] | None = None
    music: MusicInput | None = None
    sections: list[SectionInput] | None = None


def _bpm_error(bpm: float) -> str | None:
    low, high = BPM_RANGE
    if not isinstance(bpm, int | float) or not low <= bpm <= high:
        return f"BPM 必须在 {low:g}–{high:g} 之间（当前 {bpm!r}）"
    return None


def _narration_sections(
    narration: list[NarrationInput],
) -> tuple[list[Section], list[NarrationScene], float]:
    sections: list[Section] = []
    scenes: list[NarrationScene] = []
    cursor = 0.0
    for scene in narration:
        end = cursor + scene.duration_seconds
        sections.append(Section(id=scene.scene_id, label=scene.label, start=cursor, end=end))
        scenes.append(
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
    return sections, scenes, cursor


def _bar_sections(
    inputs: list[SectionInput], bpm: float, errors: list[str]
) -> tuple[list[Section], float]:
    sections: list[Section] = []
    cursor = 0.0
    seen: set[str] = set()
    for item in inputs:
        if not _ID_PATTERN.match(item.id):
            errors.append(f"镜头 id {item.id!r} 不合法：只能包含字母、数字、下划线和连字符")
            continue
        if item.id in seen:
            errors.append(f"镜头 id {item.id} 重复")
            continue
        seen.add(item.id)
        if not isinstance(item.bars, int) or isinstance(item.bars, bool) or item.bars < 1:
            errors.append(f"镜头 {item.id}：bars 必须是正整数（当前 {item.bars!r}）")
            continue
        end = cursor + item.bars * _BEATS_PER_BAR * 60.0 / bpm
        sections.append(Section(id=item.id, label=item.label, start=cursor, end=end))
        cursor = end
    return sections, cursor


def _grid(grid: GridInput, duration: float) -> Grid:
    beat = 60.0 / grid.bpm
    count = max(0, math.ceil((duration - grid.offset) / beat - _EPSILON)) + 1
    beats = [round(grid.offset + i * beat, 6) for i in range(count)]
    return Grid(
        bpm=grid.bpm,
        offset=grid.offset,
        beats=beats,
        downbeats=beats[::_BEATS_PER_BAR],
    )


def _moments(
    inputs: list[MomentInput], sections: list[Section], bpm: float, errors: list[str]
) -> list[Moment]:
    by_id = {section.id: section for section in sections}
    moments: list[Moment] = []
    for item in inputs:
        section = by_id.get(item.section_id)
        if section is None:
            errors.append(f"节拍脚本点 {item.at}：没有镜头 {item.section_id}")
            continue
        try:
            offset = parse_at(item.at, bpm, _BEATS_PER_BAR)
        except ValueError as exc:
            errors.append(f"镜头 {item.section_id} 的节拍脚本点 {item.at!r}：{exc}")
            continue
        t = section.start + offset
        if t >= section.end - _EPSILON:
            errors.append(f"镜头 {item.section_id} 的节拍脚本点 {item.at} 没有落在本段内")
            continue
        moments.append(
            Moment(
                section_id=item.section_id,
                at=item.at,
                t=round(t, 6),
                visual_action=item.visual_action,
            )
        )
    return moments


def _music(
    music: MusicInput, duration: float, grid_bpm: float | None, errors: list[str]
) -> Music | None:
    events: list[MusicEvent] = []
    for index, raw in enumerate(music.events):
        name, kind = raw.get("name"), raw.get("kind")
        start, end = raw.get("start"), raw.get("end")
        label = f"事件 {index}（{name!r}）"
        if not isinstance(name, str) or not name.strip():
            errors.append(f"事件 {index}：名称必须是非空字符串")
            continue
        if kind not in EVENT_KINDS:
            errors.append(f"{label}：kind 必须是 onset 或 sweep（当前 {kind!r}）")
            continue
        if not _finite(start) or not _finite(end) or end < start:
            errors.append(f"{label}：起止必须是数字且 start ≤ end（{start!r}→{end!r}）")
            continue
        if start < -_DURATION_TOLERANCE or end > duration + _DURATION_TOLERANCE:
            errors.append(f"{label}：起止 {start}→{end} 超出时间轴 [0, {duration:.3f}]")
            continue
        events.append(MusicEvent(name=name, kind=kind, start=float(start), end=float(end)))
    if (
        music.declared_duration is not None
        and not abs(music.declared_duration - duration) <= _DURATION_TOLERANCE
    ):
        errors.append(
            f"配乐声明的 duration {music.declared_duration} 与时间轴 {duration:.3f} "
            "相差超过 0.05 秒"
        )
    if (
        grid_bpm is not None
        and music.declared_bpm is not None
        and not abs(music.declared_bpm - grid_bpm) <= _BPM_TOLERANCE
    ):
        errors.append(f"配乐声明的 bpm {music.declared_bpm} 与节拍脚本的 {grid_bpm} 不一致")
    if (
        music.energy_hop <= 0
        or not music.energy_values
        or any(not 0.0 <= value <= 1.0 for value in music.energy_values)
    ):
        errors.append("energy：hop 必须为正，values 非空且都在 [0, 1] 内")
    return Music(
        file=MUSIC_FILE,
        events=events,
        energy=Energy(hop=music.energy_hop, values=list(music.energy_values)),
    )


def build_timeline(layers: TimelineLayers) -> Timeline:
    errors: list[str] = []
    if layers.sections is not None and layers.narration:
        raise TimelineError(["不能同时给出短片段落和旁白镜头"])
    if layers.grid is not None and (bpm_error := _bpm_error(layers.grid.bpm)):
        raise TimelineError([bpm_error])

    narration: list[NarrationScene] = []
    if layers.sections is not None:
        if layers.grid is None:
            raise TimelineError(["短片需要节拍网格（beatsheet 的 bpm）"])
        if not layers.sections:
            raise TimelineError(["没有任何镜头"])
        sections, duration = _bar_sections(layers.sections, layers.grid.bpm, errors)
    else:
        if not layers.narration:
            raise TimelineError(["没有任何镜头"])
        sections, narration, duration = _narration_sections(layers.narration)

    grid = _grid(layers.grid, duration) if layers.grid is not None else None
    moments: list[Moment] = []
    if layers.moments:
        if layers.grid is None:
            errors.append("节拍脚本点需要节拍网格")
        else:
            moments = _moments(layers.moments, sections, layers.grid.bpm, errors)
    music = None
    if layers.music is not None:
        grid_bpm = (
            layers.grid.bpm if layers.grid is not None and layers.sections is not None else None
        )
        music = _music(layers.music, duration, grid_bpm, errors)
    if errors:
        raise TimelineError(errors)
    return Timeline(
        duration=duration,
        grid=grid,
        sections=sections,
        narration=narration,
        moments=moments,
        music=music,
    )


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
            errors.append(f"第 {index} 个镜头缺少 id：镜头 id 必须是非空字符串")
            continue
        if not _ID_PATTERN.match(scene_id):
            errors.append(f"镜头 id {scene_id!r} 不合法：只能包含字母、数字、下划线和连字符")
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


def layers_from_beatsheet(
    doc: dict[str, Any],
) -> tuple[GridInput, list[SectionInput], list[MomentInput]]:
    """`beatsheet.json`（短片）→ 网格、段落、节拍脚本点。

    只做结构检查，内容校验在 `build_timeline`。
    """
    errors: list[str] = []
    bpm = doc.get("bpm")
    if isinstance(bpm, bool) or not isinstance(bpm, int | float):
        errors.append(f"beatsheet.json：bpm 必须是数字（当前 {bpm!r}）")
        bpm = 0.0
    raw_sections = doc.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        errors.append("beatsheet.json：sections 必须是非空列表")
        raise TimelineError(errors)
    sections: list[SectionInput] = []
    moments: list[MomentInput] = []
    for index, raw in enumerate(raw_sections):
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            errors.append(f"beatsheet.json：第 {index} 个段落缺少字符串 id")
            continue
        section_id = raw["id"]
        label = raw.get("label")
        bars: Any = raw.get("bars")
        sections.append(
            SectionInput(
                id=section_id,
                label=label if isinstance(label, str) and label else section_id,
                bars=bars,
            )
        )
        for moment in raw.get("moments") or []:
            if not isinstance(moment, dict) or not isinstance(moment.get("at"), str):
                errors.append(f"beatsheet.json：段落 {section_id} 有节拍脚本点缺少字符串 at")
                continue
            action = moment.get("visual_action")
            moments.append(
                MomentInput(section_id, moment["at"], action if isinstance(action, str) else "")
            )
    if errors:
        raise TimelineError(errors)
    return GridInput(float(bpm)), sections, moments


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
