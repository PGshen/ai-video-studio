"""两个业务工具共用的辅助：读时间轴、把浏览器层的异常翻成给 agent 看的中文。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from studio.agent.tools import ToolContext, ToolResult
from studio.engines.render.html.browser import ChromiumUnavailable, PageNotReady
from studio.engines.render.html.pool import PoolBusy
from studio.stages.common.music_source import find_source
from studio.timeline import TimelineError
from studio.timeline.load import TimelineSources
from studio.timeline.load import load_timeline as read_timeline

TIMELINE_PATH = "upstream/timeline.json"
ERROR_PATH = "upstream/timeline.error.txt"
_DEFAULT_REASON = "upstream/timeline.json 不存在（叙事阶段需要先定稿并完成配音）"


MAX_SHOTS = 40
"""镜头数超过它时给警告（`produce` 阶段）。"""


def _produce_timeline(ctx: ToolContext) -> tuple[dict[str, Any] | None, ToolResult | None]:
    """`produce` 阶段没有上游时间轴：镜头划分和配乐都是本阶段自己写的，每次调用即时构建。"""
    sources = TimelineSources(
        ctx.workdir,
        narration=False,
        music_source="synth" if find_source(ctx.workdir / "music") is None else "import",
        produce=True,
    )
    try:
        loaded = read_timeline(sources)
    except TimelineError as exc:
        return None, ToolResult(text=f"时间轴不可用：{exc}", is_error=True)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        reason = f"产物的结构不符合预期：{type(exc).__name__}: {exc}"
        return None, ToolResult(text=f"时间轴不可用：{reason}", is_error=True)
    return loaded.timeline.model_dump(mode="json"), None


def load_timeline(ctx: ToolContext) -> tuple[dict[str, Any] | None, ToolResult | None]:
    if ctx.stage == "produce":
        return _produce_timeline(ctx)
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
