"""`/api/projects/{id}/music/*`（子项目 3 设计 §9.1）：配乐的元数据、音频和手动渲染。

- **meta**：读 `music/` 下的托管产物；没有或损坏时 `rendered=false`。`stale` 表示产物不是对着当前
  时间轴渲染的（成片会拒绝它）。时间轴来源是工作区顶层，与成片、实时预览一致。
- **audio**：只返回 `music/music.wav`，`FileResponse` 处理 `Range`；路径走工作区的安全解析。
- **render**：不经 agent，和 `render_music` 工具共用 `render_music_core`。脚本的问题是业务结果
  （`ok=false`）；项目在跑一轮、已有手动渲染、没有沙箱、时间轴不可用是 409。

`async def` 端点：忙碌检查与登记"手动渲染中"之间不 `await`（同 `api.files` 的约定）。手动渲染期间
如果用户又开了一轮 agent，两边各自原子发布；真出现交错，`render.json` 的 `wav_hash` 对不上，
成片前置检查会点名。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import Engine

from studio.agent.runner import TurnRunner
from studio.api.deps import get_engine, get_settings, get_turn_runner
from studio.api.schemas import MusicEventOut, MusicMetaOut, MusicRenderOut, MusicSectionOut
from studio.config import Settings
from studio.db.repo.projects import get_project
from studio.stages.music import tool as music_tool
from studio.stages.music.render import metrics_of, render_music_core
from studio.stages.music.sources import section_energy
from studio.timeline import TimelineError
from studio.timeline.load import LoadedTimeline, TimelineSources, load_timeline
from studio.workspace import ScopeError, file_sha256, project_dir, safe_path

router = APIRouter(prefix="/api", tags=["music"])

_NO_STORE = {"Cache-Control": "no-store"}


def _require_score_project(engine: Engine, project_id: str) -> bool:
    """项目存在且有合成配乐，返回它是否有旁白（决定时间轴的来源）。"""
    project = get_project(engine, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")
    if project.settings.get("music_source") != "synth":
        raise HTTPException(status_code=404, detail="这个项目没有合成配乐")
    return project.settings.get("narration") is not False


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _sources(workdir: Path, narration: bool) -> TimelineSources:
    return TimelineSources(workdir, narration, "synth", with_music=False)


def _load_base(workdir: Path, narration: bool) -> LoadedTimeline | None:
    try:
        return load_timeline(_sources(workdir, narration))
    except TimelineError:
        return None


@router.get("/projects/{project_id}/music/meta", response_model=MusicMetaOut)
def music_meta_endpoint(
    project_id: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> MusicMetaOut:
    narration = _require_score_project(engine, project_id)
    workdir = project_dir(settings.data_dir, project_id)
    loaded = _load_base(workdir, narration)
    sections = (
        [
            MusicSectionOut(id=s.id, label=s.label, start=s.start, end=s.end)
            for s in loaded.timeline.sections
        ]
        if loaded is not None
        else []
    )
    music = workdir / "music"
    render = _read_json(music / "render.json")
    events_doc = _read_json(music / "events.json")
    analysis = _read_json(music / "analysis.json")
    if (
        render is None
        or events_doc is None
        or analysis is None
        or not (music / "music.wav").is_file()
    ):
        return MusicMetaOut(rendered=False, stale=False, sections=sections)
    try:
        events = [MusicEventOut(**_event(e)) for e in events_doc["events"]]
        wav_hash = file_sha256(music / "music.wav")
        return MusicMetaOut(
            rendered=True,
            # 与实时预览、成片前置检查同一标准：对着当前时间轴渲染的，且 wav 没被换过。
            stale=loaded is None
            or render.get("base_hash") != loaded.base_hash
            or render.get("wav_hash") != wav_hash,
            hash=wav_hash,
            duration=float(analysis["duration"]),
            bpm=float(render["bpm"]),
            events=events,
            sections=sections,
            waveform=[float(v) for v in analysis["waveform"]],
            metrics=analysis.get("metrics"),
        )
    except (KeyError, TypeError, ValueError):
        return MusicMetaOut(rendered=False, stale=False, sections=sections)


def _event(raw: Any) -> dict[str, Any]:
    return {k: raw[k] for k in ("name", "kind", "start", "end")}


@router.get("/projects/{project_id}/music/audio")
def music_audio_endpoint(
    project_id: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    _require_score_project(engine, project_id)
    workdir = project_dir(settings.data_dir, project_id)
    try:
        path = safe_path(workdir, "music/music.wav")
    except ScopeError as exc:
        raise HTTPException(status_code=404, detail="配乐还没有渲染") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="配乐还没有渲染")
    return FileResponse(path, media_type="audio/wav", headers=_NO_STORE)


@router.post("/projects/{project_id}/music/render", response_model=MusicRenderOut)
async def music_render_endpoint(
    project_id: str,
    request: Request,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    turn_runner: TurnRunner = Depends(get_turn_runner),
) -> MusicRenderOut:
    narration = _require_score_project(engine, project_id)
    if turn_runner.is_project_busy(project_id):
        raise HTTPException(status_code=409, detail="项目正在运行中的一轮，请等它结束再渲染")
    running: set[str] = request.app.state.music_renders
    if project_id in running:
        raise HTTPException(status_code=409, detail="这个项目的配乐正在渲染，请稍后再试")
    workdir = project_dir(settings.data_dir, project_id)
    wrap = music_tool.sandbox_wrapper(workdir)
    if wrap is None:
        raise HTTPException(status_code=409, detail="当前平台没有沙箱，不能运行合成脚本")
    try:
        loaded = load_timeline(_sources(workdir, narration))
    except TimelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    running.add(project_id)
    try:
        outcome = await render_music_core(
            workdir,
            timeline=loaded.timeline.model_dump(mode="json"),
            base_hash=loaded.base_hash,
            section_energy=section_energy(loaded.beatsheet),
            wrap_command=wrap,
        )
    finally:
        running.discard(project_id)

    picture = None
    if outcome.png is not None:
        picture = base64.b64encode(music_tool.compress_picture(outcome.png)).decode("ascii")
    report = outcome.report
    return MusicRenderOut(
        ok=outcome.ok,
        errors=outcome.errors,
        text=music_tool.format_outcome(outcome),
        warnings=list(report.warnings) if outcome.ok and report is not None else [],
        retime_note=outcome.retime_note,
        metrics=metrics_of(report) if outcome.ok and report is not None else None,
        picture_base64=picture,
        picture_media_type="image/jpeg" if picture is not None else None,
    )
