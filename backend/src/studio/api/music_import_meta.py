"""歌曲形态（MV）的 `music/meta`（子项目 4B 设计 §3.2，produce-stage 设计 §6）：只读文件，缺失或
损坏都降级成 `None` 字段。

没有 `sections.json`：网格是分析的**参考**值（BPM、第一个强拍），截取区间来自模型写的
`music/range.json`（缺省整首歌），`sections` 是模型写的镜头划分（`animation/shots.json`，成片秒）
平移到整曲秒，方便画在整首歌的波形上。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from studio.api.schemas import (
    LyricLineOut,
    MusicAnalysisOut,
    MusicEnergyOut,
    MusicGridOut,
    MusicMetaOut,
    MusicRangeOut,
    MusicSectionOut,
    MusicSourceInfo,
)
from studio.stages.common.music_source import find_source
from studio.timeline import TimelineError
from studio.timeline.imported import downbeat_times, effective_grid
from studio.timeline.lyrics import LYRICS_PATH, LyricsError, parse_lrc
from studio.timeline.shots import RANGE_PATH, SHOTS_PATH, parse_range, parse_shots
from studio.workspace import file_sha256


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def shot_sections(workdir: Path, offset: float = 0.0) -> list[MusicSectionOut]:
    """`animation/shots.json` 的镜头，起止加上 `offset`（MV：截取区间起点）；缺失或不合法为空。"""
    try:
        document = json.loads((workdir / SHOTS_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    shots = parse_shots(document, [])
    return [
        MusicSectionOut(id=s.id, label=s.label, start=s.start + offset, end=s.end + offset)
        for s in shots or []
    ]


def lyric_lines(workdir: Path, duration: float | None) -> tuple[list[LyricLineOut], str | None]:
    """`music/lyrics.lrc` in song seconds, plus why it is unusable (`None` when fine or absent)."""
    path = workdir / LYRICS_PATH
    if not path.is_file():
        return [], None
    try:
        parsed = parse_lrc(path.read_bytes(), duration if duration is not None else math.inf)
    except OSError as exc:
        return [], f"无法读取歌词文件：{exc}"
    except LyricsError as exc:
        return [], str(exc)
    return [LyricLineOut(text=x.text, start=x.start, end=x.end) for x in parsed], None


def _analysis_out(doc: dict[str, Any]) -> MusicAnalysisOut | None:
    values = {k: _number(doc.get(k)) for k in ("bpm", "confidence", "residual_ms", "duration")}
    if any(v is None for v in values.values()):
        return None
    warnings = doc.get("warnings")
    return MusicAnalysisOut(
        **{k: float(v) for k, v in values.items() if v is not None},
        warnings=[w for w in warnings if isinstance(w, str)] if isinstance(warnings, list) else [],
    )


def build_import_meta(workdir: Path) -> MusicMetaOut:
    music = workdir / "music"
    source_path = find_source(music)
    if source_path is None:
        return MusicMetaOut(form="import", rendered=False, stale=False)
    digest = file_sha256(source_path)
    analysis_doc = _read_json(music / "analysis.json")
    stale = analysis_doc is not None and analysis_doc.get("source_hash") != digest
    current = analysis_doc if analysis_doc is not None and not stale else None
    analysis = _analysis_out(current) if current is not None else None

    source = MusicSourceInfo(
        filename=source_path.name,
        size=source_path.stat().st_size,
        sha256=digest,
        duration=analysis.duration if analysis is not None else None,
    )
    grid = range_ = energy = None
    if analysis_doc is not None and analysis is not None:
        energy_values = analysis_doc.get("energy")
        hop = _number(analysis_doc.get("hop"))
        if (
            hop is not None
            and isinstance(energy_values, list)
            and all(_number(v) is not None for v in energy_values)
        ):
            energy = MusicEnergyOut(hop=hop, values=[float(v) for v in energy_values])
        try:
            bpm, offset = effective_grid(analysis_doc)
            grid = MusicGridOut(
                bpm=bpm, offset=offset, downbeats=downbeat_times(bpm, offset, analysis.duration)
            )
        except TimelineError:
            pass
    if analysis is not None:
        window = parse_range(_read_json(workdir / RANGE_PATH), analysis.duration, [])
        if window is not None:
            range_ = MusicRangeOut(start=window[0], end=window[1])
    lyrics, lyrics_error = lyric_lines(workdir, analysis.duration if analysis is not None else None)
    return MusicMetaOut(
        form="import",
        rendered=True,
        stale=stale,
        hash=digest,
        duration=analysis.duration if analysis is not None else None,
        sections=shot_sections(workdir, range_.start if range_ is not None else 0.0),
        lyrics=lyrics,
        lyrics_error=lyrics_error,
        source=source,
        analysis=analysis,
        grid=grid,
        range=range_,
        energy=energy,
    )
