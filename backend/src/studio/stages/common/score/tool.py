"""`render_music` 工具（子项目 3 设计 §7.4）：运行合成脚本，返回分析图与指标。"""

from __future__ import annotations

import base64
import hashlib
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from studio.agent.events import ImageData
from studio.agent.exec_policy import exec_mode
from studio.agent.shell_sandbox import SANDBOX_EXEC, sandbox_available, seatbelt_profile
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.config import get_settings, repo_root
from studio.engines.audio.analysis import MusicReport
from studio.engines.audio.runner import WrapCommand
from studio.stages.common.picture import compress_png
from studio.stages.common.score.render import RenderOutcome, render_music_core
from studio.stages.common.score.sources import import_source, infer_sources
from studio.timeline import TimelineError
from studio.timeline.load import load_timeline

LISTEN_NOTE = "音色、和声、混响量与声像无法由这些指标判断，需要用户试听。"
_MAX_LISTED = 8
PRODUCE_IMPORT_MESSAGE = (
    "这个项目用的是用户上传的歌曲（music/source.*），不用合成脚本：请用 analyze_music 分析歌曲，"
    "需要截取时写 music/range.json（起止秒），再写镜头划分和画面"
)


def compress_picture(png: bytes) -> bytes:
    """分析图转成 JPEG 返回给模型；`music/analysis.png` 仍是原图。大小上限见 `common.picture`。"""
    return compress_png(png)


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

exec_platform: str = sys.platform
"""`exec_mode` 用的平台；测试里替换（不改全局的 `sys.platform`）。"""

NO_SANDBOX_MESSAGE = (
    "这台机器上没有沙箱（sandbox），默认不运行 agent 写的合成脚本。"
    "如果接受风险，可以在 设置 → 通用 里打开「允许在无隔离环境执行 agent 命令」"
    "（对话里下一轮起生效）。"
)


def run_unwrapped(argv: list[str], env: dict[str, str]) -> list[str]:
    """`unsandboxed` 模式：原样运行；环境变量白名单、超时、大小检查仍由 `run_compose` 负责。"""
    return argv


def exec_wrapper(workdir: Path, *, allow_unsandboxed: bool) -> WrapCommand | None:
    """本次运行合成脚本用的包装（ADR 0024）：有 sandbox 就用；没有时开关打开则原样运行，
    否则 `None`（调用方报 `NO_SANDBOX_MESSAGE`）。agent 工具和配乐渲染接口共用。"""
    wrap = sandbox_wrapper(workdir)
    mode = exec_mode(
        platform=exec_platform,
        sandbox_available=wrap is not None,
        allow_unsandboxed=allow_unsandboxed,
    )
    if mode == "sandboxed":
        return wrap
    return run_unwrapped if mode == "unsandboxed" else None


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
    bpm = "未声明 BPM" if outcome.declared_bpm is None else f"BPM {outcome.declared_bpm:g}"
    lines = [f"配乐渲染成功：{bpm}，{outcome.event_count} 个事件。"]
    lines += _lines(outcome.report)
    if outcome.retime_note:
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
    produce = ctx.stage == "produce"
    if import_source(ctx.workdir) is not None:
        return ToolResult(text=PRODUCE_IMPORT_MESSAGE, is_error=True)
    wrap = exec_wrapper(ctx.workdir, allow_unsandboxed=ctx.allow_unsandboxed_exec)
    if wrap is None:
        return ToolResult(text=NO_SANDBOX_MESSAGE, is_error=True)
    if produce:
        # The script picks tempo, length and structure itself: no timeline in, no retime check.
        outcome = await render_music_core(ctx.workdir, wrap_command=wrap)
    else:
        try:
            loaded = load_timeline(infer_sources(ctx.workdir, "upstream/", with_music=False))
        except TimelineError as exc:
            return ToolResult(text=f"时间轴不可用：{exc}", is_error=True)
        outcome = await render_music_core(
            ctx.workdir,
            timeline=loaded.timeline.model_dump(mode="json"),
            base_hash=loaded.base_hash,
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
        jpeg = compress_picture(outcome.png)
        images.append(
            ImageData(media_type="image/jpeg", data_base64=base64.b64encode(jpeg).decode("ascii"))
        )
    return ToolResult(text=format_outcome(outcome), images=images)


RENDER_MUSIC_TOOL = ToolSpec(
    name="render_music",
    description=(
        "在沙箱里运行 music/compose.py，校验产物并返回分析图与指标。"
        "讲解与背景乐阶段会自动用另一套 BPM 或总长重跑一遍，抓写死秒数的脚本；"
        "配乐与动画阶段脚本自己决定速度、长度和结构，不重跑。"
        "你听不到声音，只能靠这张图（波形、谱图、能量、起音）和指标判断；"
        "指标只证明对齐，不证明好听。每次改动脚本后都调用一次并看图。"
        "只用于合成形态；导入形态（有 music/source.*）会报错。"
    ),
    input_model=RenderMusicArgs,
    stages={"music", "produce"},
    handler=_handler,
)
