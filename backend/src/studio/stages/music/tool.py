"""`render_music` 工具（子项目 3 设计 §7.4）：运行合成脚本，返回分析图与指标。"""

from __future__ import annotations

import base64
import hashlib
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from studio.agent.events import ImageData
from studio.agent.shell_sandbox import SANDBOX_EXEC, sandbox_available, seatbelt_profile
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.config import get_settings, repo_root
from studio.engines.audio.analysis import MusicReport
from studio.engines.audio.runner import WrapCommand
from studio.stages.music.render import RenderOutcome, render_music_core
from studio.stages.music.sources import infer_sources
from studio.timeline import TimelineError
from studio.timeline.load import load_timeline

LISTEN_NOTE = "音色、和声、混响量与声像无法由这些指标判断，需要用户试听。"
_MAX_LISTED = 8


def real_sandbox_wrapper(workdir: Path) -> WrapCommand | None:
    """Seatbelt 包装；平台没有沙箱时返回 `None`（失败关闭，不降级为无沙箱运行）。"""
    if not sandbox_available():
        return None
    profile = seatbelt_profile(
        workdir,
        [repo_root(), get_settings().data_dir],
        allow_read=[Path(sys.prefix)],  # 虚拟环境在仓库内，脚本要 import numpy；里面没有密钥
    )

    def wrap(argv: list[str], env: dict[str, str]) -> list[str]:
        return [str(SANDBOX_EXEC), "-p", profile, *argv]

    return wrap


sandbox_wrapper: Callable[[Path], WrapCommand | None] = real_sandbox_wrapper
"""测试里替换成恒等包装或 `None`。"""


def _lines(report: MusicReport) -> list[str]:
    lines = [
        f"音频：{report.duration:.3f} 秒，{report.sample_rate} Hz，"
        f"{'双' if report.channels == 2 else '单'}声道",
        f"峰值 {report.peak_dbfs:.1f} dBFS，削波样本 {report.clipped_samples}，"
        f"整体 RMS {report.rms_dbfs:.1f} dBFS",
    ]
    for section in report.sections:
        lines.append(
            f"- 段落 {section.id}：RMS {section.rms_dbfs:.1f} dBFS，"
            f"频谱重心 {section.centroid_hz:.0f} Hz"
        )
    if report.grid_alignment is None:
        lines.append(f"检测到 {len(report.onsets)} 个起音（没有网格可对齐）")
    else:
        lines.append(
            f"检测到 {len(report.onsets)} 个起音，"
            f"{report.grid_alignment:.0%} 落在 1/16 网格 ±30 ms 内"
        )
    if report.event_matches:
        parts = [
            f"{m.name} {m.matched}/{m.detectable}"
            + (f"（{m.matched / m.detectable:.0%}）" if m.detectable else "")
            for m in report.event_matches
        ]
        lines.append("声明的起音事件与实测起音匹配（±40 ms）：" + "；".join(parts))
    if report.unmatched:
        shown = report.unmatched[:_MAX_LISTED]
        lines.append("未匹配的事件：" + "、".join(f"{u['name']}@{u['start']:.2f}s" for u in shown))
    if report.undetectable:
        shown = report.undetectable[:_MAX_LISTED]
        lines.append(
            "检测不到、未计入匹配率的事件："
            + "、".join(f"{u['name']}@{u['start']:.2f}s（{u['reason']}）" for u in shown)
        )
    return lines


def format_outcome(outcome: RenderOutcome) -> str:
    if not outcome.ok:
        lines = [f"配乐渲染失败（music/ 里的旧产物没有改动），共 {len(outcome.errors)} 个问题："]
        lines += [f"- {error}" for error in outcome.errors]
        return "\n".join(lines)
    assert outcome.report is not None
    lines = [f"配乐渲染成功：BPM {outcome.declared_bpm:g}，{outcome.event_count} 个事件。"]
    lines += _lines(outcome.report)
    lines.append(outcome.retime_note)
    if outcome.report.warnings:
        lines.append(f"警告（{len(outcome.report.warnings)} 条）：")
        lines += [f"- {w}" for w in outcome.report.warnings]
    lines.append("分析图：波形、对数频率谱图、能量与起音，叠加段落、小节线和事件标记（见附图）。")
    lines.append(LISTEN_NOTE)
    return "\n".join(lines)


class RenderMusicArgs(BaseModel):
    pass


async def _handler(ctx: ToolContext, args: RenderMusicArgs) -> ToolResult:
    wrap = sandbox_wrapper(ctx.workdir)
    if wrap is None:
        return ToolResult(text="当前平台没有沙箱，不能运行合成脚本。", is_error=True)
    try:
        loaded = load_timeline(infer_sources(ctx.workdir, "upstream/", with_music=False))
    except TimelineError as exc:
        return ToolResult(text=f"时间轴不可用：{exc}", is_error=True)
    energy = {
        section["id"]: section["energy"]
        for section in (loaded.beatsheet or {}).get("sections", [])
        if isinstance(section, dict) and isinstance(section.get("energy"), str)
    }
    outcome = await render_music_core(
        ctx.workdir,
        timeline=loaded.timeline.model_dump(mode="json"),
        base_hash=loaded.base_hash,
        section_energy=energy,
        wrap_command=wrap,
    )
    if not outcome.ok:
        return ToolResult(text=format_outcome(outcome), is_error=True)
    for relpath in outcome.written:
        ctx.record_tool_write(
            relpath, hashlib.sha256((ctx.workdir / relpath).read_bytes()).hexdigest()
        )
    images = []
    if outcome.png is not None:
        images.append(
            ImageData(
                media_type="image/png", data_base64=base64.b64encode(outcome.png).decode("ascii")
            )
        )
    return ToolResult(text=format_outcome(outcome), images=images)


RENDER_MUSIC_TOOL = ToolSpec(
    name="render_music",
    description=(
        "在沙箱里运行 music/compose.py，校验产物并返回分析图与指标。"
        "会自动用另一套 BPM 或总长重跑一遍，抓写死秒数的脚本。"
        "你听不到声音，只能靠这张图（波形、谱图、能量、起音）和指标判断；"
        "指标只证明对齐，不证明好听。每次改动脚本后都调用一次并看图。"
    ),
    input_model=RenderMusicArgs,
    stages={"music"},
    handler=_handler,
)
