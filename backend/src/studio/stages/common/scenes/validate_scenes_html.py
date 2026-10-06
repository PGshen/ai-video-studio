"""`validate_scenes_html` 工具（设计 §6.3）：静态检查、冒烟运行、确定性、beat 敏感度等。

输出文本形状固定（2B 的 `scene_checks` 会解析）：错误行 `镜头 <id>：<说明>`，警告行
`警告 镜头 <id>：<说明>` / `警告：<说明>`；通过时首行 `全部 N 个镜头校验通过。`
（指定镜头时 `镜头 <id> 校验通过。`）；有错误时末行 `共 E 个错误、W 个警告。`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.engines.render.html.assemble import assemble
from studio.engines.render.html.assets import check_assets
from studio.engines.render.html.browser import BrowserClosed, PageLike
from studio.engines.render.html.glyphs import missing_characters
from studio.engines.render.html.pool import get_browser_pool
from studio.engines.render.html.probe import (
    SHIFT_MUSIC_SECONDS,
    beat_sensitivity,
    determinism_check,
    is_reel,
    music_shift_sensitivity,
    scene_sample_times,
    section_info,
    smoke_run,
)
from studio.engines.render.html.static_check import (
    StaticIssue,
    font_size_warnings,
    literal_time_warnings,
    static_check,
    strip_comments,
)
from studio.stages.common.scenes.helpers import (
    MAX_SHOTS,
    browser_error_text,
    load_timeline,
    scene_exists,
    scene_ids,
    scene_path,
)

_CUE_REFERENCE = re.compile(r"\bcue\s*\(|\bcueEnd\s*\(|\.beats\b")
_SCENE_FILE = re.compile(r"^animation/scenes/(.+)\.js$")
_DETERMINISM_SAMPLES = 6
_MOSTLY_UNCHANGED = 0.5


class ValidateScenesHtmlArgs(BaseModel):
    scene_id: str | None = None


@dataclass(slots=True)
class _Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str, scene: str | None = None) -> None:
        self.errors.append(f"镜头 {scene}：{message}" if scene else message)

    def warn(self, message: str, scene: str | None = None) -> None:
        self.warnings.append(f"警告 镜头 {scene}：{message}" if scene else f"警告：{message}")


def _issue_scene(issue: StaticIssue) -> str | None:
    match = _SCENE_FILE.match(issue.path)
    return match.group(1) if match else None


def _relevant(issue: StaticIssue, targets: list[str], single: bool) -> bool:
    scene = _issue_scene(issue)
    return not (single and scene is not None and scene not in targets)


def _lib_text(workdir: Path) -> str:
    texts = [
        p.read_text(encoding="utf-8") for p in sorted((workdir / "animation" / "lib").glob("*.js"))
    ]
    return "\n".join(texts)


def _pre_browser_checks(
    workdir: Path, timeline: dict[str, Any], targets: list[str], single: bool, report: _Report
) -> None:
    for sid in targets:
        if not scene_exists(workdir, sid):
            report.error(f"缺少镜头文件 animation/scenes/{sid}.js（或文件为空）", sid)
    for issue in static_check(workdir):
        if _relevant(issue, targets, single):
            report.error(f"{issue.path}:{issue.line} {issue.message}", _issue_scene(issue))
    for issue in font_size_warnings(workdir):
        if _relevant(issue, targets, single):
            report.warn(f"{issue.path}:{issue.line} {issue.message}", _issue_scene(issue))
    if is_reel(timeline):
        for issue in literal_time_warnings(workdir):
            if _relevant(issue, targets, single):
                report.warn(f"{issue.path}:{issue.line} {issue.message}", _issue_scene(issue))
    for message in check_assets(workdir):
        report.error(message)
    if not single:
        known = set(scene_ids(timeline))
        for path in sorted((workdir / "animation" / "scenes").glob("*.js")):
            if path.stem not in known:
                report.warn(f"animation/scenes/{path.name} 不在时间轴的镜头里，不会被渲染")

    lib = _lib_text(workdir)
    for sid in targets:
        if not scene_exists(workdir, sid):
            continue
        source = scene_path(workdir, sid).read_text(encoding="utf-8")
        _, _, beats = section_info(timeline, sid)
        if beats and not _CUE_REFERENCE.search(strip_comments(source) + "\n" + strip_comments(lib)):
            report.error(
                "有旁白 beat，但脚本（及 animation/lib/）里没有引用 env.cue / env.cueEnd / "
                "env.beats：时刻必须由 beat 推出，不能写字面量",
                sid,
            )
        text = "".join(b["cue_text"] for b in beats) + "".join(
            ch for ch in strip_comments(source) if ord(ch) > 127
        )
        missing = missing_characters(text)
        if missing:
            report.warn(f"字符 {'、'.join(missing[:10])} 不在内置字体里，可能显示成方框", sid)


async def _check_scene(page: PageLike, timeline: dict[str, Any], sid: str, report: _Report) -> None:
    smoke = await smoke_run(page, timeline, sid)
    for message in smoke.errors:
        report.error(message, sid)
    for message in smoke.warnings:
        report.warn(message, sid)
    if smoke.errors:
        return
    _, _, beats = section_info(timeline, sid)
    try:
        times = scene_sample_times(timeline, sid)[:_DETERMINISM_SAMPLES]
        unstable = await determinism_check(page, times)
        if unstable:
            report.error(
                "渲染结果依赖调用顺序或外部状态（例如 t="
                f"{unstable[0]:.2f}s 两次渲染不同）：draw 必须是 lt 的纯函数",
                sid,
            )
            return
        if not beats:
            return
        sensitivity = await beat_sensitivity(page, timeline, sid)
    except BrowserClosed:
        raise
    except Exception as exc:  # 镜头里的异常已带标签
        report.error(str(exc), sid)
        return
    if sensitivity.all_insensitive:
        report.error(
            "整个镜头对任何旁白 beat 都无反应：疑似把 beat 时刻写成了字面量，"
            "请改用 env.cue(i) / env.cueEnd(i)",
            sid,
        )
    elif sensitivity.insensitive_beats:
        names = "、".join(f"env.cue({i})" for i in sensitivity.insensitive_beats)
        report.warn(f"{names} 对应的 beat 没有驱动画面", sid)


def _scene_failed(report: _Report, sid: str) -> bool:
    return any(error.startswith(f"镜头 {sid}：") for error in report.errors)


async def _check_music_shift(
    page: PageLike, timeline: dict[str, Any], sid: str, report: _Report, *, strict: bool = True
) -> None:
    """短片：音乐整体平移后，镜头自己的关键帧应当跟着变（设计 §6.3）。

    `strict=False`（`produce` 阶段）：镜头可以有意不跟音乐，所以全部没反应也只是警告。"""
    try:
        shift = await music_shift_sensitivity(page, timeline, sid)
    except BrowserClosed:
        raise
    except Exception as exc:  # 镜头里的异常已带标签
        report.error(str(exc), sid)
        return
    if not shift.times:
        return
    if shift.all_unchanged and not strict:
        report.warn(
            f"整个镜头对音乐平移 {SHIFT_MUSIC_SECONDS:g} 秒毫无反应：疑似把时刻写成了字面量，"
            "或只靠 global.js 响应音乐；如果不是有意让它不跟音乐，请改用 env.hit / env.span / "
            "env.energy 取音乐事件",
            sid,
        )
    elif shift.all_unchanged:
        report.error(
            f"整个镜头对音乐平移 {SHIFT_MUSIC_SECONDS:g} 秒毫无反应：疑似把时刻写成了字面量，"
            "或只靠 global.js 响应节拍；请改用 env.bt / env.bar / env.hit / env.moment",
            sid,
        )
    elif len(shift.unchanged) / len(shift.times) > _MOSTLY_UNCHANGED:
        report.warn(
            f"音乐平移 {SHIFT_MUSIC_SECONDS:g} 秒后 {len(shift.unchanged)}/{len(shift.times)} "
            f"个关键帧没有变化（例如 t={shift.unchanged[0]:.2f}s）：这些位置的动作可能写死了时间",
            sid,
        )


async def _shift_pass(
    workdir: Path,
    timeline: dict[str, Any],
    targets: list[str],
    report: _Report,
    *,
    strict: bool = True,
) -> None:
    """装配时不含 `global.js` 的页面上做音乐平移检查：全局后期读节拍不能替镜头顶账。"""
    remaining = list(targets)
    can_retry = True
    while remaining:
        try:
            page_source = assemble(workdir, timeline, include_global=False)
            async with get_browser_pool().acquire(page_source) as page:
                while remaining:
                    await _check_music_shift(page, timeline, remaining[0], report, strict=strict)
                    remaining.pop(0)
                    if page.poisoned:
                        break
        except BrowserClosed as exc:
            if not can_retry:
                report.error(f"浏览器在校验过程中被关闭（已重试一次仍失败）：{exc}")
                return
            can_retry = False
        except Exception as exc:
            text = browser_error_text(exc)
            if text is None:
                raise
            report.error(text)
            return


def _report_page_errors(page: PageLike, seen: set[str], report: _Report) -> None:
    """页面加载阶段留下的错误（资源 404、lib 的告警等）不属于某个镜头，只报一次。"""
    for message in dict.fromkeys(page.errors):
        if message in seen:
            continue
        seen.add(message)
        if message.startswith("console.warning"):
            report.warn(message)
        else:
            report.error(message)


async def _browser_checks(
    workdir: Path,
    timeline: dict[str, Any],
    targets: list[str],
    report: _Report,
    *,
    strict: bool = True,
) -> None:
    remaining = list(targets)
    seen_page_errors: set[str] = set()
    can_retry = True
    reel = is_reel(timeline)
    has_global = (workdir / "animation" / "global.js").is_file()
    while remaining:
        try:
            async with get_browser_pool().acquire(assemble(workdir, timeline)) as page:
                _report_page_errors(page, seen_page_errors, report)
                while remaining:
                    sid = remaining[0]
                    await _check_scene(page, timeline, sid, report)
                    if reel and not has_global and not _scene_failed(report, sid):
                        await _check_music_shift(
                            page, timeline, sid, report, strict=strict
                        )  # 同一页面即不含全局后期
                    remaining.pop(0)
                    if page.poisoned:  # 卡死的页面不再使用，剩余镜头换新页面
                        break
        except BrowserClosed as exc:
            if not can_retry:
                report.error(f"浏览器在校验过程中被关闭（已重试一次仍失败）：{exc}")
                return
            can_retry = False  # 当前镜头没有 pop，换新页面从它重来
        except Exception as exc:
            text = browser_error_text(exc)
            if text is None:
                raise
            report.error(text)
            return


def _render(report: _Report, targets: list[str], single: bool) -> ToolResult:
    if report.errors:
        lines = [*report.errors, *report.warnings]
        lines.append(f"共 {len(report.errors)} 个错误、{len(report.warnings)} 个警告。")
        return ToolResult(text="\n".join(lines), is_error=True)
    head = f"镜头 {targets[0]} 校验通过。" if single else f"全部 {len(targets)} 个镜头校验通过。"
    return ToolResult(text="\n".join([head, *report.warnings]))


async def _handler(ctx: ToolContext, args: ValidateScenesHtmlArgs) -> ToolResult:
    timeline, failure = load_timeline(ctx)
    if timeline is None:
        assert failure is not None
        return failure
    ids = scene_ids(timeline)
    if args.scene_id is not None and args.scene_id not in ids:
        return ToolResult(
            text=f"镜头 {args.scene_id} 不在时间轴里。可用的镜头：{'、'.join(ids)}", is_error=True
        )
    single = args.scene_id is not None
    targets = [args.scene_id] if args.scene_id is not None else ids

    report = _Report()
    strict = ctx.stage != "produce"
    if not strict and len(ids) > MAX_SHOTS:
        report.warn(f"镜头数 {len(ids)} 超过 {MAX_SHOTS}：切得太碎会让每个镜头都很短、难以维护")
    _pre_browser_checks(ctx.workdir, timeline, targets, single, report)
    if not report.errors:
        await _browser_checks(ctx.workdir, timeline, targets, report, strict=strict)
        if is_reel(timeline) and (ctx.workdir / "animation" / "global.js").is_file():
            passed = [sid for sid in targets if not _scene_failed(report, sid)]
            await _shift_pass(ctx.workdir, timeline, passed, report, strict=strict)
    return _render(report, targets, single)


VALIDATE_SCENES_HTML_TOOL = ToolSpec(
    name="validate_scenes_html",
    description=(
        "校验 HTML 镜头脚本：静态规则、真实浏览器冒烟运行、确定性、beat 敏感度（有旁白）或"
        "音乐平移敏感度（短片；配乐与动画阶段只给警告）、字号与字符覆盖、资产。"
        "配乐与动画阶段会先按 animation/shots.json 与 music/ 构建时间轴。"
        "不传 scene_id 校验全部镜头。"
    ),
    input_model=ValidateScenesHtmlArgs,
    stages={"animation_html", "produce"},
    handler=_handler,
)
