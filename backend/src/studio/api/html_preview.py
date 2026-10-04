"""`/api/projects/{id}/animation/html-preview/`（子项目 2 设计 §7.1）：iframe 实时预览。

请求时现场组装页面，用工作区当前内容，不要求先拍快照；时间轴与 worker 成片同一来源
（`studio.timeline.load`）。页面里的相对 URL（`scripts/…`、`fonts/…`、`assets/…`）由同一前缀下
的资源端点供给，路径只在组装结果的页面、脚本、路由表里查，永不按路径碰磁盘。

iframe 使用 `sandbox="allow-scripts"` 且不带 `allow-same-origin`，是不透明源。画布用 `/inline`
（自包含页面）做 `srcdoc`——实测不透明源的 iframe 对本机服务的请求（连它自己的页面和脚本）会被
浏览器拦下；`/` 和资源端点保留，用于在标签页里直接打开调试，响应带 `Access-Control-Allow-Origin: *`
以便沙盒页面也能取字体；`no-store` 保证编辑后立刻生效。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Engine

from studio.api.deps import get_engine, get_settings
from studio.api.schemas import (
    HtmlPreviewAudio,
    HtmlPreviewBeat,
    HtmlPreviewMeta,
    HtmlPreviewSection,
)
from studio.config import Settings
from studio.db.repo.projects import get_project
from studio.engines.render.html.assemble import assemble, page_hash, serve_page_path
from studio.timeline import TimelineError
from studio.timeline.load import LoadedTimeline, load_workspace_timeline
from studio.workspace import project_dir

router = APIRouter(prefix="/api", tags=["html-preview"])

_HEADERS = {"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"}


def _load(engine: Engine, settings: Settings, project_id: str) -> tuple[LoadedTimeline, Path]:
    project = get_project(engine, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"项目不存在：{project_id}")
    if project.settings.get("engine") != "html":
        raise HTTPException(status_code=409, detail="这个项目不是 HTML 引擎项目，没有实时预览")
    workdir = project_dir(settings.data_dir, project_id)
    try:
        return load_workspace_timeline(workdir), workdir
    except TimelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/projects/{project_id}/animation/html-preview/meta", response_model=HtmlPreviewMeta)
def html_preview_meta_endpoint(
    project_id: str,
    response: Response,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> HtmlPreviewMeta:
    loaded, workdir = _load(engine, settings, project_id)
    response.headers.update(_HEADERS)
    timeline = loaded.timeline
    timeline_dict = timeline.model_dump(mode="json")
    by_scene = {n.scene_id: n for n in timeline.narration}
    timing_by_id = {
        scene.get("id"): scene
        for scene in loaded.timing.get("scenes", [])
        if isinstance(scene, dict)
    }

    audio: list[HtmlPreviewAudio] = []
    for section in timeline.sections:
        entry = timing_by_id.get(section.id, {})
        relpath = str(entry.get("audio_path", ""))
        if relpath and (workdir / relpath).is_file():
            version = quote(str(entry.get("audio_hash", "")), safe="")
            url = f"/api/projects/{quote(project_id, safe='')}/files/{quote(relpath, safe='/')}"
            audio.append(HtmlPreviewAudio(section_id=section.id, url=f"{url}?v={version}"))

    return HtmlPreviewMeta(
        hash=page_hash(workdir, timeline_dict),
        duration=timeline.duration,
        sections=[
            HtmlPreviewSection(
                id=section.id,
                label=section.label,
                start=section.start,
                end=section.end,
                beats=[
                    HtmlPreviewBeat(start=b.start, end=b.end, cue_text=b.cue_text)
                    for b in by_scene[section.id].beats
                ],
            )
            for section in timeline.sections
        ],
        audio=audio,
    )


@router.get("/projects/{project_id}/animation/html-preview/inline")
def html_preview_inline_endpoint(
    project_id: str,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> Response:
    """自包含的预览页（脚本内联、字体与资产是 data URI）。画布用它做 iframe 的 `srcdoc`：沙盒 iframe
    是不透明源，浏览器可能不放行它对本机服务的子资源请求（内置浏览器里实测被拦），自包含页面
    不需要任何子请求。`/` 与资源端点保留，用于在标签页里直接打开调试。"""
    loaded, workdir = _load(engine, settings, project_id)
    page = assemble(workdir, loaded.timeline.model_dump(mode="json"), preview=True, inline=True)
    return Response(content=page.html, media_type="text/html; charset=utf-8", headers=_HEADERS)


@router.get("/projects/{project_id}/animation/html-preview")
@router.get("/projects/{project_id}/animation/html-preview/")
@router.get("/projects/{project_id}/animation/html-preview/{path:path}")
def html_preview_endpoint(
    project_id: str,
    path: str = "",
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> Response:
    loaded, workdir = _load(engine, settings, project_id)
    page = assemble(workdir, loaded.timeline.model_dump(mode="json"), preview=True)
    served = serve_page_path(page, path)
    if served is None:
        raise HTTPException(status_code=404, detail=f"预览里没有这个资源：{path}")
    return Response(content=served.body, media_type=served.content_type, headers=_HEADERS)
