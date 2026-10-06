"""`render_preview_html` 工具（设计 §6.3）：单个镜头的关键时刻缩略图拼图加指标。"""

from __future__ import annotations

import base64
from typing import Any

from pydantic import BaseModel

from studio.agent.events import ImageData
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.engines.render.html.assemble import assemble
from studio.engines.render.html.browser import BrowserClosed
from studio.engines.render.html.pool import get_browser_pool
from studio.engines.render.html.probe import (
    boundary_diff,
    contact_sheet,
    frame_metrics,
    is_flat,
    section_info,
    smoke_run,
)
from studio.engines.render.html.static_check import static_check
from studio.stages.common.scenes.helpers import (
    browser_error_text,
    load_timeline,
    scene_exists,
    scene_ids,
)

BOUNDARY_NOTE_THRESHOLD = 12.0


class RenderPreviewHtmlArgs(BaseModel):
    scene_id: str


async def _pad_lines(page: Any, timeline: dict[str, Any], scene_id: str) -> list[str]:
    evaluate = getattr(page, "evaluate", None)
    if evaluate is None:
        return []
    start, end, _ = section_info(timeline, scene_id)
    pad = await evaluate(
        "id => (window.__SCENES__[id] && window.__SCENES__[id].pad) || {}", scene_id
    )
    pad_in, pad_out = float(pad.get("in", 0) or 0), float(pad.get("out", 0) or 0)
    if pad_in <= 0 and pad_out <= 0:
        return []
    line = f"pad：in={pad_in:g} out={pad_out:g}"
    notes: list[str] = []
    for label, amount, t in (
        ("in", pad_in, start - pad_in / 2),
        ("out", pad_out, end + pad_out / 2),
    ):
        if amount > 0 and 0 <= t < timeline["duration"]:
            if is_flat(frame_metrics(await page.render_jpeg(t))):
                notes.append(f"pad.{label} 叠画区间的帧空白或纯色，转场可能没有内容")
    return [line, *notes]


async def _handler(ctx: ToolContext, args: RenderPreviewHtmlArgs) -> ToolResult:
    timeline, failure = load_timeline(ctx)
    if timeline is None:
        assert failure is not None
        return failure
    ids = scene_ids(timeline)
    sid = args.scene_id
    if sid not in ids:
        return ToolResult(
            text=f"镜头 {sid} 不在时间轴里。可用的镜头：{'、'.join(ids)}", is_error=True
        )
    if not scene_exists(ctx.workdir, sid):
        return ToolResult(
            text=f"镜头 {sid}：缺少镜头文件 animation/scenes/{sid}.js（或为空），先写好再预览。",
            is_error=True,
        )
    issues = [
        f"镜头 {sid}：{i.path}:{i.line} {i.message}"
        for i in static_check(ctx.workdir)
        if i.path in (f"animation/scenes/{sid}.js", "animation/global.js")
        or i.path.startswith("animation/lib/")
    ]
    if issues:
        return ToolResult(text="\n".join(issues), is_error=True)

    start, end, _ = section_info(timeline, sid)
    index = ids.index(sid)
    attempt = 0
    while True:
        attempt += 1
        try:
            async with get_browser_pool().acquire(assemble(ctx.workdir, timeline)) as page:
                smoke = await smoke_run(page, timeline, sid)
                if smoke.errors:
                    return ToolResult(
                        text="\n".join(f"镜头 {sid}：{m}" for m in smoke.errors), is_error=True
                    )
                boundaries: list[str] = []
                if index > 0:
                    diff = await boundary_diff(page, start)
                    boundaries.append(_boundary_line("与前一镜头的边界帧差", diff))
                if index < len(ids) - 1:
                    diff = await boundary_diff(page, end)
                    boundaries.append(_boundary_line("与后一镜头的边界帧差", diff))
                pads = await _pad_lines(page, timeline, sid)
            break
        except BrowserClosed as exc:
            if attempt >= 2:
                return ToolResult(
                    text=f"浏览器在预览过程中被关闭（已重试一次仍失败）：{exc}", is_error=True
                )
        except Exception as exc:
            text = browser_error_text(exc)
            if text is None:
                raise
            return ToolResult(text=text, is_error=True)

    lines = [f"镜头 {sid} 预览：时长 {end - start:.2f}s，采样 {len(smoke.frames)} 帧。"]
    for (t, metrics), _frame in zip(smoke.metrics, smoke.frames, strict=True):
        flag = "  ← 画面空白或纯色" if is_flat(metrics) else ""
        lines.append(
            f"t={t:.2f} lt={t - start:.2f} 亮度={metrics.mean:.0f} 对比度={metrics.std:.0f}{flag}"
        )
    lines += boundaries + pads
    lines += [f"警告：{w}" for w in smoke.warnings if w.startswith("console")]
    sheet = contact_sheet([(f"t={t:.2f} lt={t - start:.2f}", jpeg) for t, jpeg in smoke.frames])
    image = ImageData(media_type="image/jpeg", data_base64=base64.b64encode(sheet).decode("ascii"))
    return ToolResult(text="\n".join(lines), images=[image])


def _boundary_line(label: str, diff: float) -> str:
    note = "；较大，若不是有意硬切请检查转场" if diff > BOUNDARY_NOTE_THRESHOLD else ""
    return f"{label}：{diff:.1f}{note}"


RENDER_PREVIEW_HTML_TOOL = ToolSpec(
    name="render_preview_html",
    description=(
        "预览单个 HTML 镜头：先做静态检查和冒烟运行，再返回关键时刻的缩略图拼图与每帧指标。"
    ),
    input_model=RenderPreviewHtmlArgs,
    stages={"animation_html"},
    handler=_handler,
)
