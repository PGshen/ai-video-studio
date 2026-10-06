"""`produce` 阶段的定稿条件与状态摘要（设计 §5.4、§5.5）。

两种形态按工作区内容分流（与 `music` 阶段同一信号）：有 `music/source.<ext>` 是 MV（用户上传的歌），
否则是短片（合成配乐）。配乐与镜头的一致性交给 `timeline.load` 的 `produce` 形态统一检查，
这里只补它看不到的：渲染记录与脚本、音频文件是否对得上，每个镜头有没有场景文件。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from studio.engines.audio.song import file_hash
from studio.stages.common.music_source import find_source
from studio.stages.common.scenes.helpers import scene_exists
from studio.timeline import TimelineError
from studio.timeline.load import TimelineSources, load_timeline
from studio.timeline.shots import RANGE_PATH, SHOTS_PATH, parse_range, parse_shots

_ANALYSIS = "music/analysis.json"
_RERENDER = "，需要重新调用 render_music"
_NOT_RENDERED = "还没有配乐：写 music/compose.py 并调用 render_music"
_NOT_ANALYZED = "歌曲还没有分析，需要先调用 analyze_music"
_REANALYZE = "源文件已更换，需要重新调用 analyze_music"


def _read_object(path: Path) -> dict[str, Any] | None:
    """`path` 的 JSON 对象；不存在、无法解析或顶层不是对象时为 `None`。"""
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return record if isinstance(record, dict) else None


def _reel_blockers(workdir: Path) -> list[str]:
    record = _read_object(workdir / "music" / "render.json")
    if record is None:
        return [_NOT_RENDERED]
    blockers: list[str] = []
    script = workdir / "music" / "compose.py"
    if not script.is_file() or file_hash(script) != record.get("script_hash"):
        blockers.append("music/compose.py 在上次渲染之后改过（或已删除）" + _RERENDER)
    wav = workdir / "music" / "music.wav"
    if not wav.is_file() or file_hash(wav) != record.get("wav_hash"):
        blockers.append("music/music.wav 缺失或与渲染记录不一致" + _RERENDER)
    for name in ("events.json", "analysis.json"):
        if not (workdir / "music" / name).is_file():
            blockers.append(f"music/{name} 缺失" + _RERENDER)
    return blockers


def _song_blockers(workdir: Path, source: Path) -> list[str]:
    analysis = _read_object(workdir / _ANALYSIS)
    if analysis is None:
        return [_NOT_ANALYZED]
    if analysis.get("source_hash") != file_hash(source):
        return [_REANALYZE]
    return []


def _shots_blockers(workdir: Path) -> tuple[list[str], list[str]]:
    """`(阻止定稿的问题, 已声明的镜头 id)`：只看 `shots.json` 自身，配乐不可用时的退路。"""
    path = workdir / SHOTS_PATH
    if not path.is_file():
        return [f"{SHOTS_PATH} 不存在：在里面写镜头划分"], []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [f"{SHOTS_PATH} 无法解析：{exc}"], []
    errors: list[str] = []
    shots = parse_shots(document, errors)
    return errors, [shot.id for shot in shots or []]


def _scene_blockers(workdir: Path, ids: list[str]) -> list[str]:
    return [
        f"animation/scenes/{scene_id}.js 不存在或是空的（镜头 {scene_id} 还没有画面）"
        for scene_id in ids
        if not scene_exists(workdir, scene_id)
    ]


def finalize_blockers(workdir: Path) -> list[str]:
    source = find_source(workdir / "music")
    music = _reel_blockers(workdir) if source is None else _song_blockers(workdir, source)
    if music:
        shot_problems, ids = _shots_blockers(workdir)
        return [*music, *shot_problems, *_scene_blockers(workdir, ids)]
    sources = TimelineSources(
        workdir,
        narration=False,
        music_source="synth" if source is None else "import",
        produce=True,
    )
    try:
        loaded = load_timeline(sources)
    except TimelineError as exc:
        _, ids = _shots_blockers(workdir)
        return [*exc.errors, *_scene_blockers(workdir, ids)]
    return _scene_blockers(workdir, [section.id for section in loaded.timeline.sections])


def _shot_count(workdir: Path) -> str:
    path = workdir / SHOTS_PATH
    if not path.is_file():
        return "还没有镜头划分"
    errors: list[str] = []
    try:
        shots = parse_shots(json.loads(path.read_text(encoding="utf-8")), errors)
    except (ValueError, OSError):
        return "shots.json 无法解析"
    return f"{len(shots)} 个镜头" if shots is not None else "shots.json 有问题"


def status_summary(workdir: Path) -> str:
    source = find_source(workdir / "music")
    shots = _shot_count(workdir)
    if source is not None:
        analysis = _read_object(workdir / _ANALYSIS)
        if analysis is None or analysis.get("source_hash") != file_hash(source):
            return f"未分析；{shots}"
        try:
            duration, bpm = float(analysis["duration"]), float(analysis["bpm"])
        except (KeyError, TypeError, ValueError):
            return f"未分析；{shots}"
        window = parse_range(_read_object(workdir / RANGE_PATH), duration, [])
        used = f"，截取 {window[1] - window[0]:.2f} 秒" if window and window[0] > 0 else ""
        return f"已分析：{duration:.2f} 秒，BPM {bpm:g}{used}；{shots}"
    record = _read_object(workdir / "music" / "render.json")
    if record is None:
        return f"未渲染；{shots}"
    events = _read_object(workdir / "music" / "events.json") or {}
    listed = events.get("events")
    count = len(listed) if isinstance(listed, list) else 0
    bpm = record.get("bpm")
    tempo = f"，BPM {bpm:g}" if isinstance(bpm, int | float) else ""
    seconds = float(record.get("duration", 0))
    return f"已渲染：{seconds:.2f} 秒{tempo}，{count} 个事件；{shots}"
