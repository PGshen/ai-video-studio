"""`final_render` 任务的 HTML 路径（子项目 2 设计 §8）。

`worker.run_once` 按项目 `settings.engine` 分流到这里。流程：读时间轴 → 前置检查（有错就失败，
不拍快照、不启动浏览器）→ 拍快照 → 无声视频（命中缓存则跳过出帧）→ 混音 → `final.json`。
渲染与混音经 `HtmlBackend` 注入，测试用假后端，不起 Chromium 和 ffmpeg。
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from studio.engines.render.html.assemble import AssembledPage, assemble
from studio.engines.render.html.assets import check_assets
from studio.engines.render.html.browser import ChromiumUnavailable, HtmlBrowser, PageNotReady
from studio.engines.render.html.static_check import static_check
from studio.engines.render.html.video import ProgressCallback, VideoRenderError, render_silent_video
from studio.engines.render.mix import AudioTrack, MixError, mix_final
from studio.jobs import heartbeat, update_progress
from studio.timeline import TimelineError
from studio.timeline.load import load_workspace_timeline
from studio.workspace import BlobStore, ScopeError, create_snapshot, safe_path

ENGINE_VERSION = "html-v1"
"""缓存键的一部分；改动出帧或编码逻辑时 bump，让旧缓存自然失效。"""
_VIDEO_PROGRESS_SHARE = 0.95
"""出帧占总进度的比例，剩下的留给混音。"""
_BEAT_INTERVAL_SECONDS = 10.0
"""没有整百分比变化时，至少隔这么久也续一次心跳。"""

RenderVideo = Callable[[AssembledPage, float, Path, int, ProgressCallback], Awaitable[None]]
Mix = Callable[[Path, list[AudioTrack], float, Path], Awaitable[None]]


class HtmlJobError(RuntimeError):
    """HTML 成片任务无法完成；消息点名镜头和原因，直接写进任务的 `error`。"""


@dataclass(frozen=True, slots=True)
class HtmlBackend:
    render_video: RenderVideo
    mix: Mix


async def _render_video(
    page: AssembledPage,
    duration: float,
    output: Path,
    fps: int,
    on_progress: ProgressCallback,
) -> None:
    async with HtmlBrowser() as browser:
        opened = await browser.open_page(page)
        try:
            await render_silent_video(opened, duration, output, fps=fps, on_progress=on_progress)
        finally:
            await opened.close()


async def _mix(video: Path, tracks: list[AudioTrack], duration: float, output: Path) -> None:
    await mix_final(video, tracks, duration, output)


def real_backend() -> HtmlBackend:
    return HtmlBackend(render_video=_render_video, mix=_mix)


@dataclass(frozen=True, slots=True)
class _AudioSource:
    scene_id: str
    path: Path
    hash: str
    start: float
    length: float


def _scene_sources(workdir: Path, scene_ids: Sequence[str], errors: list[str]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for scene_id in scene_ids:
        relpath = f"animation/scenes/{scene_id}.js"
        path = workdir / relpath
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not text.strip():
            errors.append(f"镜头 {scene_id}：缺少或为空的脚本 {relpath}")
        else:
            sources[scene_id] = text
    return sources


def _audio_sources(
    workdir: Path, timing: dict[str, Any], sections: Sequence[Any], errors: list[str]
) -> list[_AudioSource]:
    by_id = {s.get("id"): s for s in timing.get("scenes", []) if isinstance(s, dict)}
    result: list[_AudioSource] = []
    for section in sections:
        entry = by_id.get(section.id, {})
        relpath = str(entry.get("audio_path", ""))
        try:
            path = safe_path(workdir, relpath)
        except ScopeError:
            errors.append(f"镜头 {section.id}：音频路径不合法 {relpath!r}")
            continue
        if not path.is_file():
            errors.append(f"镜头 {section.id}：音频文件不存在 {relpath}")
            continue
        result.append(
            _AudioSource(
                section.id,
                path,
                str(entry.get("audio_hash", "")),
                section.start,
                section.end - section.start,
            )
        )
    return result


def _cache_path(workdir: Path, key: str) -> Path:
    return workdir / ".cache" / "render_cache" / f"{key}.mp4"


def _cache_key(page: AssembledPage, timeline_digest: str, fps: int) -> str:
    """键取自**要交给浏览器渲染的那份组装结果**（页面、脚本、路由文件的字节），不是另读一遍工作区：
    渲染期间镜头被改了，存进缓存的也是按旧内容渲染出的帧，键与内容始终对得上。"""
    digest = hashlib.sha256()
    digest.update(f"{ENGINE_VERSION}|{timeline_digest}|1920x1080|{fps}|".encode())
    digest.update(page.html.encode("utf-8"))
    for name, source in sorted(page.scripts.items()):
        digest.update(f"\0{name}\0".encode() + source.encode("utf-8"))
    for route, file in sorted(page.routes.items()):
        digest.update(f"\0{route}\0".encode() + file.read_bytes())
    return digest.hexdigest()


def _progress_reporter(engine: Engine, job_id: str) -> ProgressCallback:
    state = {"percent": -1, "beat": 0.0}

    def report(done: int, total: int) -> None:
        percent = int(done / total * 100)
        now = time.monotonic()
        if percent == state["percent"] and now - state["beat"] < _BEAT_INTERVAL_SECONDS:
            return
        state["percent"], state["beat"] = percent, now
        update_progress(engine, job_id, _VIDEO_PROGRESS_SHARE * done / total)
        heartbeat(engine, job_id)

    return report


async def run_html_job(
    engine: Engine,
    blobs: BlobStore,
    *,
    job_id: str,
    project_id: str,
    workdir: Path,
    backend: HtmlBackend,
    fps: int,
) -> None:
    """成功返回；失败抛 `HtmlJobError`，已有的 `output/final.mp4` 保持不变。"""
    try:
        loaded = load_workspace_timeline(workdir)
    except TimelineError as exc:
        raise HtmlJobError(str(exc)) from exc
    timeline = loaded.timeline.model_dump(mode="json")
    sections = loaded.timeline.sections

    errors: list[str] = []
    scene_sources = _scene_sources(workdir, [s.id for s in sections], errors)
    errors += [f"{i.path}:{i.line}：{i.message}" for i in static_check(workdir)]
    errors += check_assets(workdir)
    audio = _audio_sources(workdir, loaded.timing, sections, errors)
    if errors:
        raise HtmlJobError("成片前置检查未通过：\n" + "\n".join(f"- {e}" for e in errors))

    # 拍快照，保证 final.json 的 snapshot_id 精确对应本次渲染读到的内容。
    snapshot = create_snapshot(engine, blobs, project_id, reason="final_render")

    heartbeat(engine, job_id)
    page = assemble(workdir, timeline)
    silent = _cache_path(workdir, _cache_key(page, loaded.hash, fps))
    output_dir = workdir / "output"
    try:
        if not silent.is_file():
            await backend.render_video(
                page, float(timeline["duration"]), silent, fps, _progress_reporter(engine, job_id)
            )
        tracks = [AudioTrack(source.path, source.start, source.length) for source in audio]
        await backend.mix(silent, tracks, float(timeline["duration"]), output_dir / "final.mp4")
    except (VideoRenderError, MixError, ChromiumUnavailable, PageNotReady) as exc:
        raise HtmlJobError(f"成片渲染失败：{exc}") from exc

    meta = {
        "snapshot_id": snapshot.id,
        "engine": "html",
        "timeline_hash": loaded.hash,
        "scene_hashes": {
            scene_id: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for scene_id, text in scene_sources.items()
        },
        "audio_sources": {source.scene_id: source.hash for source in audio},
        "rendered_at": datetime.now(UTC).isoformat(),
    }
    (output_dir / "final.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
