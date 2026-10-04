"""两个业务工具共用的辅助：读时间轴、把浏览器层的异常翻成给 agent 看的中文。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from studio.agent.tools import ToolContext, ToolResult
from studio.engines.render.html.browser import ChromiumUnavailable, PageNotReady
from studio.engines.render.html.pool import PoolBusy
from studio.stages.animation_html.prepare import ERROR_PATH, TIMELINE_PATH

_DEFAULT_REASON = "upstream/timeline.json 不存在（叙事阶段需要先定稿并完成配音）"


def load_timeline(ctx: ToolContext) -> tuple[dict[str, Any] | None, ToolResult | None]:
    timeline = ctx.workdir / TIMELINE_PATH
    if timeline.is_file():
        return json.loads(timeline.read_text(encoding="utf-8")), None
    error = ctx.workdir / ERROR_PATH
    reason = error.read_text(encoding="utf-8").strip() if error.is_file() else _DEFAULT_REASON
    return None, ToolResult(text=f"时间轴不可用：{reason}", is_error=True)


def scene_ids(timeline: dict[str, Any]) -> list[str]:
    return [section["id"] for section in timeline["sections"]]


def scene_path(workdir: Path, scene_id: str) -> Path:
    return workdir / "animation" / "scenes" / f"{scene_id}.js"


def scene_exists(workdir: Path, scene_id: str) -> bool:
    path = scene_path(workdir, scene_id)
    return path.is_file() and path.read_text(encoding="utf-8").strip() != ""


def browser_error_text(exc: Exception) -> str | None:
    """能识别的浏览器层错误翻成中文；不认识的返回 `None`，由调用方继续抛出。"""
    if isinstance(exc, PageNotReady):
        return f"页面加载失败：{exc}"
    if isinstance(exc, PoolBusy | ChromiumUnavailable):
        return str(exc)
    return None
