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

from studio.engines.render.html.assemble import assemble, page_hash
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

RenderVideo = Callable[[Path, dict[str, Any], Path, int, ProgressCallback], Awaitable[None]]
Mix = Callable[[Path, list[AudioTrack], float, Path], Awaitable[None]]


class HtmlJobError(RuntimeError):
    """HTML 成片任务无法完成；消息点名镜头和原因，直接写进任务的 `error`。"""


@dataclass(frozen=True, slots=True)
class HtmlBackend:
    render_video: RenderVideo
    mix: Mix


async def _render_video(
    workdir: Path,
    timeline: dict[str, Any],
    output: Path,
    fps: int,
    on_progress: ProgressCallback,
) -> None:
    async with HtmlBrowser() as browser:
        page = await browser.open_page(assemble(workdir, timeline))
        try:
            await render_silent_video(
                page, float(timeline["duration"]), output, fps=fps, on_progress=on_progress
            )
        finally:
            await page.close()


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
            _AudioSource(section.id, path, str(entry.get("audio_hash", "")), section.start)
        )
    return result


def _cache_path(workdir: Path, key: str) -> Path:
    return workdir / ".cache" / "render_cache" / f"{key}.mp4"


def _cache_key(workdir: Path, timeline: dict[str, Any], timeline_digest: str, fps: int) -> str:
    raw = "|".join(
        [ENGINE_VERSION, page_hash(workdir, timeline), timeline_digest, "1920x1080", str(fps)]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    silent = _cache_path(workdir, _cache_key(workdir, timeline, loaded.hash, fps))
    output_dir = workdir / "output"
    try:
        if not silent.is_file():
            await backend.render_video(
                workdir, timeline, silent, fps, _progress_reporter(engine, job_id)
            )
        tracks = [AudioTrack(source.path, source.start) for source in audio]
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
