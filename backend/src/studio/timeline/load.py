"""按项目形态读出时间轴（worker 成片、预览端点、各阶段的 `prepare_turn` 共用，同一来源）。

只用 `pathlib` 读文件，不依赖 `studio.workspace`（本包是纯能力层）。所有问题——文件缺失、JSON
损坏、符号链接指向工作区外、各层不一致——都汇总成 `TimelineError`。

`TimelineSources.prefix` 区分两处读法：空串读工作区顶层（成片、worker），`"upstream/"` 读上游
物化目录（阶段的 `prepare_turn`、预览）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio.timeline.build import (
    GridInput,
    MusicInput,
    TimelineError,
    TimelineLayers,
    build_timeline,
    layers_from_beatsheet,
    narration_from_documents,
    timeline_hash,
)
from studio.timeline.schema import Timeline

_NARRATIVE = "narrative/narrative.json"
_TIMING = "narrative/timing.json"
_BEATSHEET = "beatsheet/beatsheet.json"
_EVENTS = "music/events.json"
_ANALYSIS = "music/analysis.json"


@dataclass(frozen=True, slots=True)
class TimelineSources:
    root: Path
    narration: bool
    music_source: str
    """`none` / `synth` / `import`；只有 `synth` 会读配乐文件。"""
    prefix: str = ""
    with_music: bool = True
    """`False` 给配乐阶段自己用：不含 `music` 层的时间轴，是合成脚本的输入。"""


@dataclass(frozen=True, slots=True)
class LoadedTimeline:
    timeline: Timeline
    hash: str
    base_hash: str
    """不含 `music` 层的时间轴哈希；`music/render.json` 用它判断配乐是否对应当前时间轴。"""
    narrative: dict[str, Any]
    timing: dict[str, Any]
    beatsheet: dict[str, Any] | None


def _read_document(root: Path, relpath: str, hint: str) -> dict[str, Any]:
    path = root / relpath
    if not path.is_file():
        raise TimelineError([f"{relpath} 不存在（{hint}）"])
    if not path.resolve().is_relative_to(root.resolve()):
        raise TimelineError([f"{relpath} 指向工作区之外，不能读取"])
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TimelineError([f"{relpath} 无法解析：{exc}"]) from exc
    if not isinstance(document, dict):
        raise TimelineError([f"{relpath} 的顶层不是对象"])
    return document


def _music_input(events_doc: dict[str, Any], analysis_doc: dict[str, Any]) -> MusicInput:
    events = events_doc.get("events")
    energy = analysis_doc.get("energy")
    hop = analysis_doc.get("hop")
    if not isinstance(events, list):
        raise TimelineError(["music/events.json：events 必须是列表"])
    if not isinstance(energy, list) or isinstance(hop, bool) or not isinstance(hop, int | float):
        raise TimelineError(["music/analysis.json：需要 hop（数字）和 energy（列表）"])
    declared_duration = events_doc.get("duration")
    declared_bpm = events_doc.get("bpm")
    return MusicInput(
        events=events,
        energy_hop=float(hop),
        energy_values=[float(v) for v in energy],
        declared_duration=float(declared_duration)
        if isinstance(declared_duration, int | float)
        else None,
        declared_bpm=float(declared_bpm) if isinstance(declared_bpm, int | float) else None,
    )


def load_timeline(sources: TimelineSources) -> LoadedTimeline:
    root, prefix = sources.root, sources.prefix
    narrative: dict[str, Any] = {}
    timing: dict[str, Any] = {}
    beatsheet: dict[str, Any] | None = None

    if sources.narration:
        narrative = _read_document(root, f"{prefix}{_NARRATIVE}", "叙事阶段需要先定稿并完成配音")
        timing = _read_document(root, f"{prefix}{_TIMING}", "叙事阶段需要先定稿并完成配音")
        base = TimelineLayers(narration_from_documents(narrative, timing))
    else:
        beatsheet = _read_document(root, f"{prefix}{_BEATSHEET}", "节拍脚本阶段需要先定稿")
        grid, sections, moments = layers_from_beatsheet(beatsheet)
        base = TimelineLayers([], grid=grid, moments=moments, sections=sections)
    base_timeline = build_timeline(base)
    base_hash = timeline_hash(base_timeline)

    if not (sources.with_music and sources.music_source == "synth"):
        return LoadedTimeline(base_timeline, base_hash, base_hash, narrative, timing, beatsheet)

    hint = "配乐阶段需要先渲染并定稿"
    events_doc = _read_document(root, f"{prefix}{_EVENTS}", hint)
    analysis_doc = _read_document(root, f"{prefix}{_ANALYSIS}", hint)
    music = _music_input(events_doc, analysis_doc)
    grid_input = base.grid
    if sources.narration:
        bpm, offset = events_doc.get("bpm"), events_doc.get("offset", 0.0)
        if isinstance(bpm, bool) or not isinstance(bpm, int | float):
            raise TimelineError(["music/events.json：有旁白的项目必须声明数字 bpm"])
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int | float)
            or not 0 <= offset < max(base_timeline.duration, 0.001)
        ):
            raise TimelineError(
                [f"music/events.json：offset 必须是 [0, {base_timeline.duration:.3f}) 秒内的数字"]
            )
        grid_input = GridInput(float(bpm), float(offset))
    full = TimelineLayers(
        base.narration,
        grid=grid_input,
        moments=base.moments,
        music=music,
        sections=base.sections,
    )
    timeline = build_timeline(full)
    return LoadedTimeline(
        timeline, timeline_hash(timeline), base_hash, narrative, timing, beatsheet
    )


def load_workspace_timeline(workdir: Path) -> LoadedTimeline:
    """无配乐讲解（子项目 2 的形态）的读取入口，保持原签名。"""
    return load_timeline(TimelineSources(workdir, narration=True, music_source="none"))
