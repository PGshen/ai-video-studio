"""`render_music` 的核心流程（子项目 3 设计 §7.4）：运行脚本、校验、重定时校验、写回产物。

不 import `agent`：沙箱包装由调用方传入，工具（`tool.py`）和 3B 的 api 端点共用这一份核心。
任何一步失败都不改动 `music/` 里的旧产物；临时目录总是清理。
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studio import fsretry
from studio.engines.audio.analysis import DURATION_TOLERANCE, MusicReport, analyze, validate_events
from studio.engines.audio.picture import render_analysis_png
from studio.engines.audio.runner import ComposeError, WrapCommand, run_compose
from studio.engines.audio.wav import AudioError, Samples, read_wav

PRODUCTS = ("music.wav", "events.json", "analysis.json", "analysis.png", "render.json")
RETIME_FACTOR = 1.25
"""重定时：所有时间乘 1.25（短片的 BPM 相应乘 0.8）。"""
_MIN_ALIGNMENT_RATIO = 0.5
_TIMEOUT = 120.0


@dataclass(slots=True)
class RenderOutcome:
    ok: bool
    errors: list[str] = field(default_factory=list)
    report: MusicReport | None = None
    png: bytes | None = None
    retime_note: str = ""
    written: list[str] = field(default_factory=list)
    """成功时写入（或更新）的 `music/` 下的相对路径。"""
    declared_bpm: float | None = None
    event_count: int = 0


@dataclass(slots=True)
class _Run:
    samples: Samples
    doc: dict[str, Any]
    report: MusicReport
    wav_path: Path
    events_path: Path
    analysis_timeline: dict[str, Any]


def retime_timeline(timeline: Mapping[str, Any], factor: float = RETIME_FACTOR) -> dict[str, Any]:
    """所有时间乘 `factor`，网格 BPM 除以 `factor`：写死了秒数或 BPM 的脚本在这条时间轴上会露馅。"""
    scaled = copy.deepcopy(dict(timeline))
    scaled["duration"] = timeline["duration"] * factor
    for section in scaled.get("sections", []):
        section["start"] *= factor
        section["end"] *= factor
    for scene in scaled.get("narration", []):
        scene["start"] *= factor
        scene["end"] *= factor
        for beat in scene.get("beats", []):
            beat["start"] *= factor
            beat["end"] *= factor
    for moment in scaled.get("moments", []):
        moment["t"] *= factor
    grid = scaled.get("grid")
    if grid:
        grid["bpm"] = grid["bpm"] / factor
        grid["offset"] *= factor
        grid["beats"] = [t * factor for t in grid["beats"]]
        grid["downbeats"] = [t * factor for t in grid["downbeats"]]
    return scaled


def _with_declared_grid(timeline: dict[str, Any], doc: Mapping[str, Any]) -> dict[str, Any]:
    """没有网格的时间轴（有旁白的项目、`produce`）：分析对齐率时用脚本声明的 BPM 与偏移补一个；
    脚本没声明 BPM 就不补，对齐率为空。"""
    if timeline.get("grid") or doc.get("bpm") is None:
        return timeline
    return {
        **timeline,
        "grid": {
            "bpm": float(doc["bpm"]),
            "offset": float(doc.get("offset", 0.0)),
            "beats": [],
            "downbeats": [],
        },
    }


async def _run_and_check(
    script: Path,
    timeline: dict[str, Any] | None,
    run_dir: Path,
    *,
    wrap_command: WrapCommand,
    timeout: float,
) -> _Run | list[str]:
    """`timeline=None`：`produce` 阶段，脚本不收到时间轴，长度以音频本身为准。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    timeline_path: Path | None = None
    if timeline is not None:
        timeline_path = run_dir / "timeline.json"
        timeline_path.write_text(
            json.dumps(timeline, ensure_ascii=False), encoding="utf-8", newline=""
        )
    try:
        result = await run_compose(
            script, timeline_path, run_dir, timeout=timeout, wrap_command=wrap_command
        )
        samples = await asyncio.to_thread(read_wav, result.wav_path)
    except (ComposeError, AudioError) as exc:
        return [str(exc)]
    try:
        doc = json.loads(result.events_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"STUDIO_OUT_EVENTS 写出的不是合法的 JSON：{exc}"]
    free = timeline is None
    if timeline is None:
        timeline = {"duration": samples.duration}
    problems = validate_events(doc, timeline, bpm_required=not free)
    if abs(samples.duration - timeline["duration"]) > DURATION_TOLERANCE:
        problems.append(
            f"音频时长 {samples.duration:.3f} 秒与时间轴 {timeline['duration']:.3f} 秒"
            f"相差超过 {DURATION_TOLERANCE:g} 秒"
        )
    if problems:
        return problems
    analysis_timeline = _with_declared_grid(timeline, doc)
    report = await asyncio.to_thread(analyze, samples, analysis_timeline, doc["events"])
    return _Run(samples, doc, report, result.wav_path, result.events_path, analysis_timeline)


_MIN_RETIMED_ONSET_SHARE = 0.8
_RETIME_TOLERANCE = 0.06  # seconds; scripts may round or jitter slightly


def _names(run: _Run) -> set[str]:
    return {str(event["name"]) for event in run.doc["events"]}


def _retime_problems(first: _Run, second: _Run | list[str], timeline: dict[str, Any]) -> list[str]:
    reel = bool(timeline.get("grid")) and not timeline.get("narration")
    what = (
        f"BPM 改成 {timeline['grid']['bpm'] / RETIME_FACTOR:g}、总长改成 "
        f"{timeline['duration'] * RETIME_FACTOR:.2f} 秒"
        if reel
        else f"总长改成 {timeline['duration'] * RETIME_FACTOR:.2f} 秒"
    )
    head = f"脚本似乎写死了时间：{what}后重跑"
    if isinstance(second, list):
        return [f"{head}没有通过：" + "；".join(second)]
    problems: list[str] = []
    if _names(first) != _names(second):
        problems.append(
            f"{head}后事件名集合变了（{sorted(_names(first))} → {sorted(_names(second))}）"
        )
    before, after = first.report.grid_alignment, second.report.grid_alignment
    if reel and before and (after or 0.0) < before * _MIN_ALIGNMENT_RATIO:
        problems.append(f"{head}后起音与网格的对齐率从 {before:.0%} 掉到 {(after or 0.0):.0%}")
    if reel:
        share = _retimed_onset_share(first, second)
        if share < _MIN_RETIMED_ONSET_SHARE:
            problems.append(
                f"{head}后只有 {share:.0%} 的起音事件按 {RETIME_FACTOR:g} 倍挪动"
                "（所有时间应随 BPM 同比例变化）"
            )
    return problems


def _onsets(run: _Run) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    for event in run.doc["events"]:
        if event.get("kind") == "onset":
            found.setdefault(str(event["name"]), []).append(float(event["start"]))
    return found


def _retimed_onset_share(first: _Run, second: _Run) -> float:
    """Share of declared onsets that reappear at `RETIME_FACTOR` times their start (per name).
    Grid alignment alone cannot tell: at high BPM the dense 1/16 grid forgives misplaced hits."""
    before, after = _onsets(first), _onsets(second)
    total = sum(len(starts) for starts in before.values())
    if not total:
        return 1.0
    kept = 0
    for name, starts in before.items():
        later = after.get(name, [])
        kept += sum(
            any(abs(start * RETIME_FACTOR - other) <= _RETIME_TOLERANCE for other in later)
            for start in starts
        )
    return kept / total


def metrics_of(report: MusicReport) -> dict[str, Any]:
    return {
        "peak_dbfs": round(report.peak_dbfs, 2),
        "clipped_samples": report.clipped_samples,
        "rms_dbfs": round(report.rms_dbfs, 2),
        "sections": [
            {"id": s.id, "rms_dbfs": round(s.rms_dbfs, 2), "centroid_hz": round(s.centroid_hz)}
            for s in report.sections
        ],
        "grid_alignment": None
        if report.grid_alignment is None
        else round(report.grid_alignment, 3),
        "onsets": len(report.onsets),
        "event_matches": [
            {"name": m.name, "detectable": m.detectable, "matched": m.matched}
            for m in report.event_matches
        ],
        "undetectable": len(report.undetectable),
        "warnings": list(report.warnings),
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _publish(music_dir: Path, files: dict[str, bytes]) -> None:
    """先把全部文件写成临时文件，再依次改名：中途失败不留下半套新产物。"""
    music_dir.mkdir(parents=True, exist_ok=True)
    temps = {}
    try:
        for name, data in files.items():
            temp = music_dir / f".{name}.tmp"
            temp.write_bytes(data)
            temps[name] = temp
        for name, temp in temps.items():
            fsretry.replace(temp, music_dir / name)
    finally:
        for temp in temps.values():
            temp.unlink(missing_ok=True)


async def render_music_core(
    workdir: Path,
    *,
    timeline: dict[str, Any] | None = None,
    base_hash: str | None = None,
    wrap_command: WrapCommand,
    timeout: float = _TIMEOUT,
) -> RenderOutcome:
    """`timeline=None` 是 `produce` 阶段：脚本没有时间轴输入，自己决定速度、长度和结构，
    所以不做重定时校验，`render.json` 里没有 `base_hash`，`bpm` 可以不声明。"""
    script = workdir / "music" / "compose.py"
    if not script.is_file():
        return RenderOutcome(ok=False, errors=["music/compose.py 不存在，先写合成脚本"])
    script_bytes = script.read_bytes()
    run_root = workdir / ".cache" / "tmp" / f"music-run-{uuid.uuid4().hex[:8]}"
    try:
        run_root.mkdir(parents=True, exist_ok=True)
        script = run_root / "compose.py"  # run the bytes that get hashed, whoever edits meanwhile
        script.write_bytes(script_bytes)
        first = await _run_and_check(
            script, timeline, run_root / "main",
            wrap_command=wrap_command, timeout=timeout,
        )  # fmt: skip
        if isinstance(first, list):
            return RenderOutcome(ok=False, errors=first)

        second: _Run | None = None
        retimed: dict[str, Any] | None = None
        if timeline is not None:
            retimed = retime_timeline(timeline)
            retime_run = await _run_and_check(
                script, retimed, run_root / "retime",
                wrap_command=wrap_command, timeout=timeout,
            )  # fmt: skip
            problems = _retime_problems(first, retime_run, timeline)
            if problems:
                return RenderOutcome(ok=False, errors=problems, report=first.report)
            assert not isinstance(retime_run, list)
            second = retime_run
        duration = float(first.analysis_timeline["duration"])

        wav_bytes = first.wav_path.read_bytes()
        events_bytes = first.events_path.read_bytes()
        png = await asyncio.to_thread(
            render_analysis_png,
            first.report,
            first.analysis_timeline,
            first.doc["events"],
            first.samples,
        )
        wav_hash = _sha256(wav_bytes)
        report = first.report
        analysis = {
            "hop": report.energy_hop,
            "energy": report.energy,
            "duration": duration,
            "sample_rate": report.sample_rate,
            "waveform": report.waveform,
            "metrics": metrics_of(report),
            "wav_hash": wav_hash,
        }
        render: dict[str, Any] = {"script_hash": _sha256(script_bytes)}
        if base_hash is not None:
            render["base_hash"] = base_hash
        render |= {
            "wav_hash": wav_hash,
            "bpm": first.doc.get("bpm"),
            "duration": duration,
            "rendered_at": datetime.now(UTC).isoformat(),
        }
        _publish(
            workdir / "music",
            {
                "music.wav": wav_bytes,
                "events.json": events_bytes,
                "analysis.json": json.dumps(analysis, ensure_ascii=False, allow_nan=False).encode(
                    "utf-8"
                ),
                "analysis.png": png,
                "render.json": json.dumps(
                    render, ensure_ascii=False, indent=2, allow_nan=False
                ).encode("utf-8"),
            },
        )
        note = ""
        if second is not None and retimed is not None and timeline is not None:
            before = first.report.grid_alignment
            after = second.report.grid_alignment
            note = (
                f"重定时校验通过：总长 {timeline['duration']:.2f}→{retimed['duration']:.2f} 秒，"
                f"事件名一致"
                + (f"，起音对齐率 {before:.0%}→{(after or 0):.0%}" if before is not None else "")
            )
        declared = first.doc.get("bpm")
        return RenderOutcome(
            ok=True,
            report=report,
            png=png,
            retime_note=note,
            written=[f"music/{name}" for name in PRODUCTS],
            declared_bpm=float(declared) if declared is not None else None,
            event_count=len(first.doc["events"]),
        )
    finally:
        shutil.rmtree(run_root, ignore_errors=True)
