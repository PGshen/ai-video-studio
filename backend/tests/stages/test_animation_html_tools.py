"""`validate_scenes_html` 与 `render_preview_html`（子项目 2 设计 §6.3）。

非 `slow` 用例用假浏览器按脚本驱动，覆盖检查表的逻辑与输出文本形状；`slow` 用例用真实 Chromium。
"""

from __future__ import annotations

import base64
import copy
import io
import json
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from fixtures.html_engine import projects as fx
from fixtures.html_engine.fakes import Behaviour, ScriptedBrowser
from fixtures.html_engine.fakes import beat_starts as _beat_starts
from fixtures.html_engine.fakes import digest as _digest
from fixtures.html_engine.fakes import jpeg as _jpeg
from studio.agent.tools import ToolContext, ToolResult, invoke_tool
from studio.engines.render.html.browser import (
    BrowserClosed,
    ChromiumUnavailable,
    PageNotReady,
    RenderTimeout,
    SceneRenderError,
)
from studio.engines.render.html.pool import BrowserPool, PoolBusy, set_browser_pool
from studio.stages.animation_html import STAGE
from studio.stages.common.scenes.render_preview_html import RENDER_PREVIEW_HTML_TOOL
from studio.stages.common.scenes.validate_scenes_html import VALIDATE_SCENES_HTML_TOOL


@pytest.fixture
async def behaviour() -> AsyncIterator[Behaviour]:
    b = Behaviour()

    async def launcher() -> ScriptedBrowser:
        return ScriptedBrowser(b)

    pool = BrowserPool(launcher=launcher)
    set_browser_pool(pool)
    yield b
    set_browser_pool(None)
    await pool.close()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "timeline.json").write_text(
        json.dumps(fx.TIMELINE, ensure_ascii=False), encoding="utf-8"
    )
    fx.write_project(tmp_path, scenes={"s-hook": fx.CUE_SCENE, "s-explain": fx.CUE_SCENE})
    return tmp_path


def _ctx(workdir: Path) -> ToolContext:
    return ToolContext(
        project_id="p",
        stage="animation_html",
        workdir=workdir,
        record_tool_write=lambda relpath, sha256: None,
    )


async def _validate(workdir: Path, **args: Any) -> ToolResult:
    return await invoke_tool(VALIDATE_SCENES_HTML_TOOL, _ctx(workdir), args)


async def _preview(workdir: Path, **args: Any) -> ToolResult:
    return await invoke_tool(RENDER_PREVIEW_HTML_TOOL, _ctx(workdir), args)


def _set_timeline(workdir: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    timeline = copy.deepcopy(fx.TIMELINE)
    mutate(timeline)
    (workdir / "upstream" / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")


# ---- 注册 -------------------------------------------------------------------------------


def test_tools_are_scoped_and_registered_on_the_stage() -> None:
    assert VALIDATE_SCENES_HTML_TOOL.stages == {"animation_html"}
    assert RENDER_PREVIEW_HTML_TOOL.stages == {"animation_html"}
    assert {t.name for t in STAGE.tools()} == {
        "validate_scenes_html",
        "render_preview_html",
        "suggest_upstream_change",
    }


# ---- validate：前置条件 ----------------------------------------------------------------


@pytest.mark.parametrize("tool", ["validate", "preview"])
async def test_missing_timeline_is_reported_with_the_recorded_reason(
    tmp_path: Path, behaviour: Behaviour, tool: str
) -> None:
    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "timeline.error.txt").write_text(
        "缺少上游叙事产物\n", encoding="utf-8"
    )
    result = await (
        _validate(tmp_path) if tool == "validate" else _preview(tmp_path, scene_id="s-hook")
    )
    assert result.is_error
    assert "时间轴不可用" in result.text and "缺少上游叙事产物" in result.text
    assert behaviour.opened == 0


async def test_missing_timeline_without_reason_file_has_a_default_message(
    tmp_path: Path, behaviour: Behaviour
) -> None:
    result = await _validate(tmp_path)
    assert result.is_error and "时间轴不可用" in result.text


async def test_unknown_scene_id_lists_valid_ids(project: Path, behaviour: Behaviour) -> None:
    result = await _validate(project, scene_id="nope")
    assert result.is_error and "s-hook" in result.text and "s-explain" in result.text


async def test_missing_and_empty_scene_files_are_reported_by_id(
    project: Path, behaviour: Behaviour
) -> None:
    (project / "animation" / "scenes" / "s-explain.js").write_text("  \n", encoding="utf-8")
    (project / "animation" / "scenes" / "s-hook.js").unlink()
    result = await _validate(project)
    assert result.is_error
    assert "镜头 s-hook：" in result.text and "镜头 s-explain：" in result.text
    assert behaviour.opened == 0


async def test_single_scene_validation_ignores_other_missing_scenes(
    project: Path, behaviour: Behaviour
) -> None:
    (project / "animation" / "scenes" / "s-explain.js").unlink()
    result = await _validate(project, scene_id="s-hook")
    assert not result.is_error
    assert result.text.splitlines()[0] == "镜头 s-hook 校验通过。"


# ---- validate：成功形状与静态检查 ------------------------------------------------------------


async def test_all_pass_shape(project: Path, behaviour: Behaviour) -> None:
    result = await _validate(project)
    assert not result.is_error
    assert result.text.splitlines()[0] == "全部 2 个镜头校验通过。"
    assert result.images == []


async def test_static_violation_is_an_error_with_file_and_line_and_skips_the_browser(
    project: Path, behaviour: Behaviour
) -> None:
    source = fx.CUE_SCENE + "\nconst r = Math.random();\n"
    (project / "animation" / "scenes" / "s-hook.js").write_text(source, encoding="utf-8")
    result = await _validate(project)
    assert result.is_error
    assert (
        "镜头 s-hook：animation/scenes/s-hook.js:" in result.text and "Math.random" in result.text
    )
    assert behaviour.opened == 0
    assert result.text.splitlines()[-1].startswith("共 ")


async def test_lib_violation_is_reported_without_a_scene_prefix(
    project: Path, behaviour: Behaviour
) -> None:
    fx.write_project(project, scenes={}, lib={"u": "const d = new Date();\n"})
    result = await _validate(project)
    assert result.is_error and "animation/lib/u.js:1" in result.text


# ---- validate：cue 引用、敏感度、确定性 -----------------------------------------------------


async def test_scene_without_any_cue_reference_is_an_error(
    project: Path, behaviour: Behaviour
) -> None:
    (project / "animation" / "scenes" / "s-hook.js").write_text(fx.LITERAL_SCENE, encoding="utf-8")
    result = await _validate(project, scene_id="s-hook")
    assert result.is_error
    assert "镜头 s-hook：" in result.text and "env.cue" in result.text


async def test_a_cue_reference_in_lib_satisfies_the_check(
    project: Path, behaviour: Behaviour
) -> None:
    (project / "animation" / "scenes" / "s-hook.js").write_text(fx.LITERAL_SCENE, encoding="utf-8")
    fx.write_project(project, scenes={}, lib={"c": "const first = env => env.cue(0);\n"})
    result = await _validate(project, scene_id="s-hook")
    assert "env.cue" not in result.text


async def test_scene_insensitive_to_every_beat_is_an_error(
    project: Path, behaviour: Behaviour
) -> None:
    behaviour.hash_fn = lambda t, tl: _digest(t)
    result = await _validate(project, scene_id="s-hook")
    assert result.is_error
    assert "镜头 s-hook：整个镜头对任何旁白 beat 都无反应" in result.text


async def test_scene_insensitive_to_some_beats_is_a_warning(
    project: Path, behaviour: Behaviour
) -> None:
    behaviour.hash_fn = lambda t, tl: _digest(t, tl["narration"][0]["beats"][0]["start"])
    result = await _validate(project, scene_id="s-hook")
    assert not result.is_error
    assert "警告 镜头 s-hook：" in result.text and "env.cue(1)" in result.text


async def test_order_dependent_rendering_is_an_error(project: Path, behaviour: Behaviour) -> None:
    counter = {"n": 0}

    def hash_fn(t: float, tl: Mapping[str, Any]) -> str:
        counter["n"] += 1
        return _digest(t, counter["n"], _beat_starts(tl))

    behaviour.hash_fn = hash_fn
    result = await _validate(project, scene_id="s-hook")
    assert result.is_error and "依赖调用顺序" in result.text


# ---- validate：冒烟、页面、浏览器错误 ---------------------------------------------------------


async def test_scene_exception_is_prefixed_with_scene_id(
    project: Path, behaviour: Behaviour
) -> None:
    def jpeg(t: float) -> bytes:
        raise SceneRenderError(f"[scene s-hook @lt={t:.3f}] TypeError: boom")

    behaviour.jpeg_fn = jpeg
    result = await _validate(project, scene_id="s-hook")
    assert result.is_error
    assert "镜头 s-hook：[scene s-hook @lt=" in result.text and "boom" in result.text


async def test_page_not_ready_names_the_broken_file(project: Path, behaviour: Behaviour) -> None:
    behaviour.open_error = PageNotReady(
        "脚本加载出错",
        ["pageerror: SyntaxError (http://studio.local/scripts/animation/lib/b.js:1)"],
    )
    result = await _validate(project)
    assert result.is_error and "页面加载失败" in result.text and "lib/b.js" in result.text


async def test_render_timeout_is_named(project: Path, behaviour: Behaviour) -> None:
    def jpeg(t: float) -> bytes:
        raise RenderTimeout(t, 10.0)

    behaviour.jpeg_fn = jpeg
    result = await _validate(project, scene_id="s-hook")
    assert result.is_error and "镜头 s-hook 在 lt=" in result.text and "渲染超时" in result.text


async def test_pool_busy_and_missing_chromium_are_readable(
    project: Path, behaviour: Behaviour
) -> None:
    behaviour.open_error = PoolBusy(60)
    busy = await _validate(project)
    assert busy.is_error and "预览繁忙" in busy.text
    behaviour.open_error = ChromiumUnavailable()
    missing = await _validate(project)
    assert missing.is_error and "uv run playwright install chromium" in missing.text


# ---- validate：页面作废、页面级错误、浏览器中途关闭 --------------------------------------------


async def test_a_hung_scene_does_not_make_later_scenes_fail(
    project: Path, behaviour: Behaviour
) -> None:
    def jpeg(t: float) -> bytes:
        if t < 3.0:  # s-hook 的区间
            raise RenderTimeout(t, 10.0)
        return _jpeg()

    behaviour.jpeg_fn = jpeg
    result = await _validate(project)
    assert result.is_error
    assert "镜头 s-hook 在 lt=" in result.text and "渲染超时" in result.text
    assert "镜头 s-explain：" not in result.text
    assert behaviour.opened == 2  # 作废的页面不再使用，剩余镜头换新页面


async def test_page_level_errors_are_reported_once_without_a_scene_prefix(
    project: Path, behaviour: Behaviour
) -> None:
    behaviour.page_errors = ["console.error: Failed to load resource: 404 (fonts/x.woff2)"]
    result = await _validate(project)
    assert result.is_error
    assert result.text.count("Failed to load resource") == 1
    assert (
        "镜头 s-hook：console" not in result.text and "镜头 s-explain：console" not in result.text
    )


async def test_a_browser_closed_mid_call_is_retried_once_on_a_fresh_page(
    project: Path, behaviour: Behaviour
) -> None:
    calls = {"n": 0}

    def jpeg(t: float) -> bytes:
        calls["n"] += 1
        if calls["n"] == 1:
            raise BrowserClosed("Target page, context or browser has been closed")
        return _jpeg()

    behaviour.jpeg_fn = jpeg
    result = await _validate(project)
    assert not result.is_error, result.text
    assert behaviour.opened == 2


async def test_a_browser_that_keeps_closing_is_reported_after_one_retry(
    project: Path, behaviour: Behaviour
) -> None:
    def jpeg(t: float) -> bytes:
        raise BrowserClosed("Target page, context or browser has been closed")

    behaviour.jpeg_fn = jpeg
    result = await _validate(project)
    assert result.is_error and "浏览器" in result.text and "已重试一次" in result.text
    assert behaviour.opened == 2


async def test_preview_retries_once_when_the_browser_closes_mid_call(
    project: Path, behaviour: Behaviour
) -> None:
    calls = {"n": 0}

    def jpeg(t: float) -> bytes:
        calls["n"] += 1
        if calls["n"] == 1:
            raise BrowserClosed("Target page, context or browser has been closed")
        return _jpeg()

    behaviour.jpeg_fn = jpeg
    result = await _preview(project, scene_id="s-hook")
    assert not result.is_error, result.text
    assert len(result.images) == 1


# ---- validate：警告 -------------------------------------------------------------------------


async def test_warnings_for_flat_frames_small_fonts_and_missing_glyphs(
    project: Path, behaviour: Behaviour
) -> None:
    behaviour.jpeg_fn = lambda t: _jpeg(flat=True)
    source = fx.CUE_SCENE + "\nctx.font = '10px Anton'; const s = '龘';\n"
    (project / "animation" / "scenes" / "s-hook.js").write_text(source, encoding="utf-8")
    result = await _validate(project, scene_id="s-hook")
    assert not result.is_error
    assert "警告 镜头 s-hook：" in result.text
    assert "空白或纯色" in result.text and "10px" in result.text and "龘" in result.text


async def test_asset_problems_are_errors_and_unknown_scene_files_warn(
    project: Path, behaviour: Behaviour
) -> None:
    fx.write_project(project, scenes={"s-extra": fx.PURE_SCENE_PLAIN}, assets={"clip.mp4": "x"})
    result = await _validate(project)
    assert result.is_error and "clip.mp4" in result.text
    assert "警告：" in result.text and "s-extra" in result.text
    single = await _validate(project, scene_id="s-hook")
    assert "s-extra" not in single.text


# ---- preview --------------------------------------------------------------------------------


def _sheet(result: ToolResult) -> Image.Image:
    assert len(result.images) == 1 and result.images[0].media_type == "image/jpeg"
    return Image.open(io.BytesIO(base64.b64decode(result.images[0].data_base64)))


async def test_preview_returns_one_contact_sheet_and_metrics(
    project: Path, behaviour: Behaviour
) -> None:
    result = await _preview(project, scene_id="s-hook")
    assert not result.is_error
    sheet = _sheet(result)
    assert sheet.width == 4 * 480 and sheet.height % 270 == 0
    assert "镜头 s-hook" in result.text and "采样" in result.text
    assert "t=" in result.text and "lt=" in result.text


async def test_preview_unknown_scene_and_missing_file(project: Path, behaviour: Behaviour) -> None:
    unknown = await _preview(project, scene_id="nope")
    assert unknown.is_error and "s-hook" in unknown.text
    (project / "animation" / "scenes" / "s-hook.js").unlink()
    missing = await _preview(project, scene_id="s-hook")
    assert missing.is_error and "s-hook" in missing.text and missing.images == []


async def test_preview_does_not_draw_when_checks_fail(project: Path, behaviour: Behaviour) -> None:
    (project / "animation" / "scenes" / "s-hook.js").write_text(
        fx.CUE_SCENE + "\nfetch('x');\n", encoding="utf-8"
    )
    static = await _preview(project, scene_id="s-hook")
    assert static.is_error and static.images == [] and "fetch" in static.text

    (project / "animation" / "scenes" / "s-hook.js").write_text(fx.CUE_SCENE, encoding="utf-8")

    def jpeg(t: float) -> bytes:
        raise SceneRenderError("[scene s-hook @lt=0.050] boom")

    behaviour.jpeg_fn = jpeg
    smoke = await _preview(project, scene_id="s-hook")
    assert smoke.is_error and smoke.images == [] and "boom" in smoke.text


async def test_preview_marks_flat_frames_and_large_boundary_diffs(
    project: Path, behaviour: Behaviour
) -> None:
    behaviour.jpeg_fn = lambda t: _jpeg(flat=t < 3.0)
    result = await _preview(project, scene_id="s-explain")
    assert not result.is_error
    assert "较大，若不是有意硬切请检查转场" in result.text
    first = await _preview(project, scene_id="s-hook")
    assert "空白或纯色" in first.text


async def test_preview_reports_pad_values(project: Path, behaviour: Behaviour) -> None:
    behaviour.pads = {"in": 0.5, "out": 0.0}
    result = await _preview(project, scene_id="s-explain")
    assert "pad" in result.text and "in=0.5" in result.text


async def test_preview_pool_errors_are_readable(project: Path, behaviour: Behaviour) -> None:
    behaviour.open_error = ChromiumUnavailable()
    result = await _preview(project, scene_id="s-hook")
    assert result.is_error and "uv run playwright install chromium" in result.text


# ---- slow：真实 Chromium --------------------------------------------------------------------


@pytest.fixture
async def real_pool() -> AsyncIterator[None]:
    pool = BrowserPool()
    set_browser_pool(pool)
    yield
    set_browser_pool(None)
    await pool.close()


@pytest.mark.slow
async def test_real_browser_correct_scenes_pass(tmp_path: Path, real_pool: None) -> None:
    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "timeline.json").write_text(json.dumps(fx.TIMELINE), encoding="utf-8")
    fx.write_project(tmp_path, scenes={"s-hook": fx.CUE_SCENE, "s-explain": fx.CUE_SCENE})
    result = await _validate(tmp_path)
    assert not result.is_error, result.text
    assert result.text.splitlines()[0] == "全部 2 个镜头校验通过。"
    preview = await _preview(tmp_path, scene_id="s-explain")
    assert not preview.is_error, preview.text
    assert _sheet(preview).width == 4 * 480


@pytest.mark.slow
async def test_real_browser_violations_are_caught(tmp_path: Path, real_pool: None) -> None:
    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "timeline.json").write_text(json.dumps(fx.TIMELINE), encoding="utf-8")
    fx.write_project(
        tmp_path,
        scenes={"s-hook": fx.LITERAL_SCENE, "s-explain": fx.THROWING_SCENE},
    )
    literal = await _validate(tmp_path)
    assert literal.is_error
    assert "镜头 s-hook：" in literal.text and "env.cue" in literal.text

    fx.write_project(tmp_path, scenes={"s-hook": fx.CUE_SCENE})
    thrown = await _validate(tmp_path)
    assert thrown.is_error
    assert "镜头 s-explain：" in thrown.text and "[scene s-explain" in thrown.text


# ---- 短片（无旁白，音乐驱动）：音乐平移检查与关键时刻预览（子项目 3 设计 §6.3） ----

_REEL_SCENE = (
    "module.exports = { draw(ctx, lt, env) { ctx.fillRect(0, 0, 10 + env.hit('kick'), 10); } };\n"
)


@pytest.fixture
def reel(tmp_path: Path) -> Path:
    from fixtures.html_engine.projects import reel_timeline

    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "timeline.json").write_text(
        json.dumps(reel_timeline(), ensure_ascii=False), encoding="utf-8"
    )
    fx.write_project(
        tmp_path,
        scenes={"s1": _REEL_SCENE, "s2": _REEL_SCENE},
        global_js="module.exports = { post(ctx, t, env) {} };\n",
    )
    return tmp_path


def _follows_the_grid(t: float, tl: Mapping[str, Any]) -> str:
    return _digest(t, tl["grid"]["beats"][:3], tl["moments"][0]["t"])


async def test_reel_scene_that_follows_the_music_passes(reel: Path, behaviour: Behaviour) -> None:
    behaviour.hash_fn = _follows_the_grid
    result = await _validate(reel)
    assert not result.is_error, result.text
    assert "全部 2 个镜头校验通过" in result.text


async def test_the_music_shift_check_runs_on_a_page_without_global_js(
    reel: Path, behaviour: Behaviour
) -> None:
    behaviour.hash_fn = _follows_the_grid
    await _validate(reel)
    with_global = [p for p in behaviour.assembled if "animation/global.js" in p.scripts]
    without = [p for p in behaviour.assembled if "animation/global.js" not in p.scripts]
    assert (
        with_global and without
    )  # the normal checks keep the global pass; the shift check drops it


async def test_without_a_global_script_one_page_is_enough(reel: Path, behaviour: Behaviour) -> None:
    (reel / "animation" / "global.js").unlink()
    behaviour.hash_fn = _follows_the_grid
    await _validate(reel)
    assert behaviour.opened == 1


async def test_reel_scene_that_ignores_the_music_is_an_error(
    reel: Path, behaviour: Behaviour
) -> None:
    behaviour.hash_fn = lambda t, tl: _digest(t)
    result = await _validate(reel, scene_id="s1")
    assert result.is_error
    assert "镜头 s1：整个镜头对音乐平移 0.2 秒毫无反应" in result.text
    assert "global.js" in result.text and "env.bt" in result.text


async def test_reel_scene_that_ignores_most_of_the_music_is_a_warning(
    reel: Path, behaviour: Behaviour
) -> None:
    def hash_fn(t: float, tl: Mapping[str, Any]) -> str:
        return _digest(t, tl["moments"][0]["t"]) if t < 0.5 else _digest(t)

    behaviour.hash_fn = hash_fn
    result = await _validate(reel, scene_id="s1")
    assert not result.is_error, result.text
    assert "警告 镜头 s1：" in result.text and "音乐平移" in result.text


async def test_a_literal_time_comparison_is_a_warning_for_reels_only(
    reel: Path, behaviour: Behaviour
) -> None:
    behaviour.hash_fn = _follows_the_grid
    (reel / "animation" / "scenes" / "s1.js").write_text(
        "module.exports = { draw(ctx, lt, env) { if (lt > 3.5) ctx.fillRect(0, 0, 1, 1); } };\n"
    )
    result = await _validate(reel, scene_id="s1")
    assert not result.is_error
    assert "警告 镜头 s1：animation/scenes/s1.js:1" in result.text and "字面量" in result.text


async def test_reel_scenes_do_not_get_the_beat_checks(reel: Path, behaviour: Behaviour) -> None:
    behaviour.hash_fn = _follows_the_grid
    result = await _validate(reel)
    assert "旁白 beat" not in result.text and "env.cue" not in result.text


async def test_reel_preview_samples_moments_and_downbeats(reel: Path, behaviour: Behaviour) -> None:
    from fixtures.html_engine.projects import reel_timeline

    timeline = reel_timeline()
    result = await _preview(reel, scene_id="s2")
    assert not result.is_error, result.text
    lines = [line for line in result.text.splitlines() if line.startswith("t=")]
    seen = [float(line.split()[0][2:]) for line in lines]
    moment = timeline["moments"][1]["t"]
    assert any(abs(t - (moment + 0.04)) < 0.01 for t in seen)
    section = timeline["sections"][1]
    assert all(section["start"] <= t < section["end"] for t in seen)
    assert len(result.images) == 1


@pytest.mark.slow
async def test_real_browser_reel_global_post_cannot_vouch_for_a_scene(
    tmp_path: Path, real_pool: None
) -> None:
    from fixtures.html_engine.projects import reel_timeline

    (tmp_path / "upstream").mkdir()
    (tmp_path / "upstream" / "timeline.json").write_text(
        json.dumps(reel_timeline()), encoding="utf-8"
    )
    follows = (
        "module.exports = { draw(ctx, lt, env) {\n"
        "  ctx.fillStyle = '#102030'; ctx.fillRect(0, 0, env.W, env.H);\n"
        "  ctx.fillStyle = '#fff';\n"
        "  ctx.fillRect(100, 100, 200 + 600 * env.hit('kick'), 120);\n"
        "} };\n"
    )
    ignores = (
        "module.exports = { draw(ctx, lt, env) {\n"
        "  ctx.fillStyle = '#102030'; ctx.fillRect(0, 0, env.W, env.H);\n"
        "  ctx.fillStyle = '#fff'; ctx.fillRect(100 + lt * 50, 100, 200, 120);\n"
        "} };\n"
    )
    # A HUD that reads the grid on every frame: it would make every frame change.
    hud = (
        "module.exports = { post(ctx, t, env) {\n"
        "  const bar = Math.floor((t - env.grid.beats[0]) / (240 / env.grid.bpm));\n"
        "  ctx.fillStyle = '#f00'; ctx.fillRect(1800, 20, 10 + bar, 10);\n"
        "  ctx.fillRect(1700, 20, 10 + 40 * (env.grid.beats[1] - env.grid.beats[0]), 10);\n"
        "} };\n"
    )
    fx.write_project(tmp_path, scenes={"s1": follows, "s2": ignores}, global_js=hud)
    result = await _validate(tmp_path)
    assert result.is_error, result.text
    assert "镜头 s2：整个镜头对音乐平移" in result.text
    assert "镜头 s1：" not in result.text
    ok = await _validate(tmp_path, scene_id="s1")
    assert not ok.is_error, ok.text
    preview = await _preview(tmp_path, scene_id="s1")
    assert not preview.is_error, preview.text
