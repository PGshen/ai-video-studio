"""真实 Chromium 下的 HTML 引擎运行时契约（`-m slow`，设计 §5.2）。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, cast

import pytest

from fixtures.html_engine import projects as fx
from studio.engines.render.html.assemble import assemble
from studio.engines.render.html.browser import (
    HtmlBrowser,
    HtmlPage,
    PageNotReady,
    RenderTimeout,
    SceneRenderError,
)
from studio.engines.render.html.pool import BrowserPool
from studio.engines.render.html.probe import (
    beat_sensitivity,
    determinism_check,
    frame_metrics,
)

pytestmark = pytest.mark.slow

_PIXEL = (
    "([x, y]) => Array.from(document.getElementById('c').getContext('2d')"
    ".getImageData(x, y, 1, 1).data)"
)


async def _open(browser: HtmlBrowser, workdir: Path, **kwargs: object) -> HtmlPage:
    page = await browser.open_page(assemble(workdir, fx.TIMELINE))
    assert isinstance(page, HtmlPage)
    return page


@pytest.fixture
async def browser():
    async with HtmlBrowser(ready_timeout=15, render_timeout=3) as b:
        yield b


async def _pixel(page: HtmlPage, t: float, x: int, y: int) -> list[int]:
    await page.render_hash(t)
    return await page.evaluate(_PIXEL, [x, y])


async def test_env_contract_values(browser: HtmlBrowser, tmp_path: Path) -> None:
    fx.write_project(tmp_path, scenes={"s-hook": fx.CUE_SCENE, "s-explain": fx.CUE_SCENE})
    page = await _open(browser, tmp_path)
    await page.render_hash(4.0)
    seen = await page.evaluate("window.__seen")
    assert seen["s-explain"] == {
        "cue0": pytest.approx(0.5),
        "cueEnd0": pytest.approx(1.5),
        "len": 3.0,
        "id": "s-explain",
        "index": 1,
        "W": 1920,
        "H": 1080,
        "beats": 2,
        "t": 4.0,
    }
    await page.close()


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        (fx.THROWING_SCENE, "只有 2 个 beat"),
        (fx.GRID_SCENE, "没有节拍网格"),
        (fx.NO_DRAW_SCENE, "没有导出 draw"),
    ],
)
async def test_scene_errors_carry_scene_label(
    browser: HtmlBrowser, tmp_path: Path, source: str, needle: str
) -> None:
    fx.write_project(tmp_path, scenes={"s-hook": source})
    page = await _open(browser, tmp_path)
    with pytest.raises(SceneRenderError) as exc:
        await page.render_jpeg(1.0)
    assert "[scene s-hook" in str(exc.value) and needle in str(exc.value)
    if source is fx.THROWING_SCENE:
        assert "@lt=1.000" in str(exc.value)
    await page.close()


async def test_pad_keeps_previous_scene_visible_then_hides_it(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    fx.write_project(tmp_path, scenes={"s-hook": fx.PAD_A, "s-explain": fx.PAD_B})
    page = await _open(browser, tmp_path)
    assert (await _pixel(page, 3.2, 20, 20))[:3] == [255, 0, 0]
    assert (await _pixel(page, 3.2, 210, 20))[:3] == [0, 0, 255]
    assert (await _pixel(page, 3.7, 20, 20))[:3] == [0, 0, 0]
    assert (await _pixel(page, 2.9, 210, 20))[:3] == [0, 0, 0]
    await page.close()


async def test_global_post_runs_after_scenes(browser: HtmlBrowser, tmp_path: Path) -> None:
    fx.write_project(
        tmp_path,
        scenes={"s-hook": fx.PURE_SCENE_PLAIN},
        global_js=fx.GLOBAL_POST,
    )
    page = await _open(browser, tmp_path)
    assert (await _pixel(page, 1.0, 8, 8))[:3] == [255, 0, 255]
    await page.close()


async def test_assets_are_predecoded_and_missing_ones_are_named(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    fx.write_project(
        tmp_path,
        scenes={"s-hook": fx.ASSET_SCENE, "s-explain": fx.MISSING_ASSET_SCENE},
        assets={"logo.svg": fx.SVG_RED},
    )
    page = await _open(browser, tmp_path)
    assert (await _pixel(page, 1.0, 50, 50))[:3] == [255, 0, 0]
    with pytest.raises(SceneRenderError) as exc:
        await page.render_jpeg(4.0)
    assert "nope.svg" in str(exc.value)
    await page.close()


async def test_bundled_chinese_font_renders_text(browser: HtmlBrowser, tmp_path: Path) -> None:
    fx.write_project(tmp_path, scenes={"s-hook": fx.CHINESE_SCENE})
    page = await _open(browser, tmp_path)
    assert frame_metrics(await page.render_jpeg(1.0)).std > 10
    assert await page.evaluate("document.fonts.check(\"700 40px 'Noto Sans SC'\", '天空')")
    await page.close()


async def test_determinism_pure_scene_and_stateful_scene(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    fx.write_project(
        tmp_path, scenes={"s-hook": fx.PURE_SCENE_PLAIN, "s-explain": fx.PURE_SCENE_PLAIN}
    )
    page = await _open(browser, tmp_path)
    assert await determinism_check(page, [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]) == []
    await page.close()

    stateful = tmp_path / "stateful"
    fx.write_project(stateful, scenes={"s-hook": fx.STATEFUL_SCENE})
    page = await _open(browser, stateful)
    assert await determinism_check(page, [0.5, 1.5, 2.5]) != []
    await page.close()


async def test_beat_sensitivity_distinguishes_cue_driven_from_literal_times(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    fx.write_project(tmp_path, scenes={"s-hook": fx.CUE_SCENE, "s-explain": fx.LITERAL_SCENE})
    page = await _open(browser, tmp_path)
    driven = await beat_sensitivity(page, fx.TIMELINE, "s-hook")
    assert driven.tested == [0, 1] and driven.insensitive_beats == []
    literal = await beat_sensitivity(page, fx.TIMELINE, "s-explain")
    assert literal.all_insensitive
    await page.close()


async def test_syntax_error_in_a_scene_fails_fast_and_names_the_file(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    fx.write_project(tmp_path, scenes={"s-hook": fx.SYNTAX_ERROR_SCENE})
    started = time.monotonic()
    with pytest.raises(PageNotReady) as exc:
        await _open(browser, tmp_path)
    assert time.monotonic() - started < 15
    assert "s-hook.js" in str(exc.value)


async def test_duplicate_top_level_declaration_in_lib_is_reported(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    fx.write_project(
        tmp_path,
        scenes={"s-hook": fx.PURE_SCENE_PLAIN},
        lib={"a": "const PAL = 1;\n", "b": "const PAL = 2;\n"},
    )
    with pytest.raises(PageNotReady) as exc:
        await _open(browser, tmp_path)
    assert "b.js" in str(exc.value)


async def test_infinite_loop_times_out_and_poisons_the_page(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    fx.write_project(tmp_path, scenes={"s-hook": fx.LOOP_SCENE})
    page = await _open(browser, tmp_path)
    with pytest.raises(RenderTimeout):
        await page.render_jpeg(1.0)
    assert page.poisoned


async def test_pool_recovers_after_chromium_is_killed_and_after_a_hang(tmp_path: Path) -> None:
    good, hung = tmp_path / "good", tmp_path / "hung"
    fx.write_project(good, scenes={"s-hook": fx.PURE_SCENE_PLAIN})
    fx.write_project(hung, scenes={"s-hook": fx.LOOP_SCENE})

    async def launcher() -> HtmlBrowser:
        return await HtmlBrowser(render_timeout=2).start()

    pool = BrowserPool(launcher=launcher)
    good_page = assemble(good, fx.TIMELINE)
    try:
        async with pool.acquire(good_page) as page:
            assert frame_metrics(await page.render_jpeg(1.0)).std > 0
        assert pool._browser is not None
        await cast(Any, pool._browser)._browser.close()  # 模拟 Chromium 被杀
        async with pool.acquire(good_page) as page:
            assert frame_metrics(await page.render_jpeg(1.0)).std > 0

        with pytest.raises(RenderTimeout):
            async with pool.acquire(assemble(hung, fx.TIMELINE)) as page:
                await page.render_jpeg(1.0)
        async with pool.acquire(good_page) as page:
            assert frame_metrics(await page.render_jpeg(1.0)).std > 0
    finally:
        await pool.close()


async def test_style_fonts_are_loaded_before_ready(browser: HtmlBrowser, tmp_path: Path) -> None:
    from studio.engines.render.html.assemble import FONTS_DIR

    scene = (
        "module.exports = { draw(ctx, lt, env) {"
        " ctx.fillStyle = '#000'; ctx.fillRect(0, 0, env.W, env.H);"
        " ctx.fillStyle = '#fff'; ctx.font = '120px Brand'; ctx.fillText('ABC', 100, 400); } };"
    )
    fx.write_project(tmp_path, scenes={"s-hook": scene})
    font = tmp_path / "style" / "fonts" / "Brand.woff2"
    font.parent.mkdir(parents=True)
    font.write_bytes((FONTS_DIR / "anton.woff2").read_bytes())
    page = await _open(browser, tmp_path)
    statuses = await page.evaluate("[...document.fonts].map(f => f.status)")
    assert statuses and all(status == "loaded" for status in statuses)
    assert await determinism_check(page, [0.5, 1.0]) == []
    await page.close()


async def test_non_ascii_asset_names_are_served(browser: HtmlBrowser, tmp_path: Path) -> None:
    scene = (
        "module.exports = { draw(ctx, lt, env) {"
        " ctx.drawImage(env.assets['中文 logo.svg'], 0, 0, 100, 100); } };"
    )
    fx.write_project(tmp_path, scenes={"s-hook": scene}, assets={"中文 logo.svg": fx.SVG_RED})
    page = await _open(browser, tmp_path)
    assert (await _pixel(page, 1.0, 50, 50))[:3] == [255, 0, 0]
    await page.close()


async def test_inline_page_renders_the_same_frames_as_the_route_served_page(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    """实时预览用的自包含页面（脚本内联、字体与资产是 data URI）和成片用的页面渲染结果一致。"""
    fx.write_project(
        tmp_path,
        scenes={"s-hook": fx.CHINESE_SCENE, "s-explain": fx.ASSET_SCENE},
        assets={"logo.svg": fx.SVG_RED},
    )
    served = await browser.open_page(assemble(tmp_path, fx.TIMELINE))
    inline = await browser.open_page(assemble(tmp_path, fx.TIMELINE, preview=True, inline=True))
    try:
        for t in (0.5, 2.0, 3.5, 5.5):
            assert await served.render_hash(t) == await inline.render_hash(t), t
        assert inline.errors == []
    finally:
        await served.close()
        await inline.close()
