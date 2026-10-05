"""导入形态的 `music/meta`（子项目 4B 设计 §3.2）：只读文件，缺失或损坏都降级成 `None` 字段。

有效网格与有效区间走 `studio.timeline.imported` 的同一套规则，这里不重算。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from studio.api.schemas import (
    MusicAnalysisOut,
    MusicEnergyOut,
    MusicGridOut,
    MusicMetaOut,
    MusicRangeOut,
    MusicSectionOut,
    MusicSourceInfo,
    SectionsCheckOut,
)
from studio.stages.common.music_source import find_source
from studio.stages.music.validate_sections import check_workspace
from studio.timeline import TimelineError
from studio.timeline.imported import downbeat_times, effective_grid, effective_range
from studio.workspace import file_sha256


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _sections(doc: dict[str, Any] | None) -> list[MusicSectionOut]:
    result: list[MusicSectionOut] = []
    raw = doc.get("sections") if doc is not None else None
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            return []
        start, end = _number(item.get("start")), _number(item.get("end"))
        if start is None or end is None or not isinstance(item.get("id"), str):
            return []
        label = item.get("label")
        result.append(
            MusicSectionOut(
                id=item["id"], label=label if isinstance(label, str) else "", start=start, end=end
            )
        )
    return result


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
    sections_doc = _read_json(music / "sections.json")
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
        if hop is not None and isinstance(energy_values, list):
            energy = MusicEnergyOut(hop=hop, values=[float(v) for v in energy_values])
        try:
            bpm, offset = effective_grid(analysis_doc, sections_doc or {})
            grid = MusicGridOut(
                bpm=bpm, offset=offset, downbeats=downbeat_times(bpm, offset, analysis.duration)
            )
        except TimelineError:
            pass
    if sections_doc is not None:
        try:
            start, end = effective_range(sections_doc)
            range_ = MusicRangeOut(start=start, end=end)
        except TimelineError:
            pass
    check = check_workspace(workdir)
    return MusicMetaOut(
        form="import",
        rendered=True,
        stale=stale,
        hash=digest,
        duration=analysis.duration if analysis is not None else None,
        sections=_sections(sections_doc),
        source=source,
        analysis=analysis,
        grid=grid,
        range=range_,
        energy=energy,
        sections_check=SectionsCheckOut(ok=check.ok, errors=check.errors, warnings=check.warnings),
    )
