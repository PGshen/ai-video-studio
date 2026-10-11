"""Shared WebGL context for scenes: `env.gl()` / `env.three()` in real Chromium (ADR 0028)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fixtures.html_engine import projects as fx
from studio.engines.render.html.assemble import assemble
from studio.engines.render.html.browser import (
    HtmlBrowser,
    HtmlPage,
    SceneRenderError,
    is_driver_performance_note,
)
from studio.engines.render.html.probe import determinism_check


@pytest.mark.parametrize(
    ("text", "noise"),
    [
        (
            "[.WebGL-0x10400438a00]GL Driver Message (OpenGL, Performance, GL_CLOSE_PATH_NV, "
            "High): GPU stall due to ReadPixels",
            True,
        ),
        (
            "[.WebGL-0x1]GL Driver Message (OpenGL, Performance, GL_CLOSE_PATH_NV, High): "
            "GPU stall due to ReadPixels (this message will no longer repeat)",
            True,
        ),
        ("[.WebGL-0x1]GL_INVALID_OPERATION: glDrawElements: Insufficient buffer size.", False),
        ("THREE.WebGLRenderer: Context Lost.", False),
    ],
)
def test_driver_performance_notes_are_not_scene_errors(text: str, noise: bool) -> None:
    assert is_driver_performance_note(text) is noise


_PIXEL = (
    "([x, y]) => Array.from(document.getElementById('c').getContext('2d')"
    ".getImageData(x, y, 1, 1).data)"
)


def three_scene(color: str, clear: str | None = None) -> str:
    """A lit torus knot whose pose comes only from `lt`; optionally sets a clear color."""
    set_clear = f"r.setClearColor({clear}, 1);" if clear else ""
    return f"""
const scene = new THREE.Scene();
const cam = new THREE.PerspectiveCamera(45, 16 / 9, 0.1, 100);
cam.position.set(0, 0, 6);
const mesh = new THREE.Mesh(
  new THREE.TorusKnotGeometry(1.2, 0.35, 160, 24),
  new THREE.MeshStandardMaterial({{ color: {color}, roughness: 0.4 }}),
);
scene.add(mesh, new THREE.AmbientLight(0xffffff, 0.4));
const sun = new THREE.DirectionalLight(0xffffff, 2.5);
sun.position.set(3, 4, 5);
scene.add(sun);
window.__renderers = window.__renderers || new Set();
module.exports = {{ draw(ctx, lt, env) {{
  ctx.fillStyle = '#123456'; ctx.fillRect(0, 0, env.W, env.H);
  const r = env.three();
  window.__renderers.add(r);
  {set_clear}
  mesh.rotation.set(lt * 0.9, lt * 0.6, 0);
  r.render(scene, cam);
  ctx.drawImage(r.domElement, 0, 0);
}} }};
"""


# Counts WebGL contexts created by anything after it (libs load before the runtime).
_COUNT_GL_LIB = """
window.__glContexts = 0;
const __getContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function (kind, opts) {
  if (String(kind).startsWith('webgl')) window.__glContexts += 1;
  return __getContext.call(this, kind, opts);
};
"""


@pytest.fixture
async def browser():
    async with HtmlBrowser(ready_timeout=20, render_timeout=10) as b:
        yield b


async def _open(browser: HtmlBrowser, workdir: Path) -> HtmlPage:
    page = await browser.open_page(assemble(workdir, fx.TIMELINE))
    assert isinstance(page, HtmlPage)
    return page


@pytest.mark.slow
async def test_scenes_share_one_three_renderer_and_frames_are_deterministic(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    fx.write_project(
        tmp_path,
        scenes={
            "s-hook": three_scene("0xff4422", clear="0x000000"),
            "s-explain": three_scene("0x22aaff"),
        },
        lib={"count": _COUNT_GL_LIB},
    )
    page = await _open(browser, tmp_path)
    times = [x * 0.37 % 6 for x in range(30)]  # jumps back and forth between the two scenes
    assert await determinism_check(page, times) == []
    first = [await page.render_hash(t) for t in times]
    assert await page.evaluate("[window.__renderers.size, window.__glContexts]") == [1, 1]
    # The 3D object is visible over the 2D background.
    await page.render_hash(1.0)
    center = await page.evaluate(_PIXEL, [960, 540])
    assert center[0] > center[2], center
    assert page.errors == []
    await page.close()

    again = await _open(browser, tmp_path)
    assert [await again.render_hash(t) for t in times] == first
    await again.close()


@pytest.mark.slow
async def test_renderer_state_does_not_leak_between_scenes(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    """Scene A sets an opaque black clear color; scene B relies on the default (transparent), so
    its 2D background must show through regardless of which scene rendered before."""
    fx.write_project(
        tmp_path,
        scenes={
            "s-hook": three_scene("0xff4422", clear="0x000000"),
            "s-explain": three_scene("0x22aaff"),
        },
    )
    page = await _open(browser, tmp_path)
    corners = []
    for t in (4.0, 1.0, 4.0):
        await page.render_hash(t)
        corners.append(await page.evaluate(_PIXEL, [5, 5]))
    assert corners == [[0x12, 0x34, 0x56, 255], [0, 0, 0, 255], [0x12, 0x34, 0x56, 255]]
    await page.close()


@pytest.mark.slow
async def test_raw_gl_canvas_is_cleared_for_each_scene(
    browser: HtmlBrowser, tmp_path: Path
) -> None:
    scene = """
module.exports = { draw(ctx, lt, env) {
  const { gl, canvas } = env.gl();
  if (lt < 1) { gl.clearColor(1, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT); }
  ctx.fillStyle = '#00ff00'; ctx.fillRect(0, 0, env.W, env.H);
  ctx.drawImage(canvas, 0, 0);
} };
"""
    fx.write_project(tmp_path, scenes={"s-hook": scene})
    page = await _open(browser, tmp_path)
    await page.render_hash(0.5)
    assert (await page.evaluate(_PIXEL, [5, 5]))[:3] == [255, 0, 0]
    await page.render_hash(2.0)
    assert (await page.evaluate(_PIXEL, [5, 5]))[:3] == [0, 255, 0]
    await page.close()


@pytest.mark.slow
async def test_three_is_explained_when_not_assembled(browser: HtmlBrowser, tmp_path: Path) -> None:
    scene = "module.exports = { draw(ctx, lt, env) { env.three(); } };\n"
    fx.write_project(tmp_path, scenes={"s-hook": scene})
    page = await _open(browser, tmp_path)
    with pytest.raises(SceneRenderError, match="THREE"):
        await page.render_hash(1.0)
    await page.close()


@pytest.mark.slow
async def test_2d_pages_create_no_webgl_context(browser: HtmlBrowser, tmp_path: Path) -> None:
    fx.write_project(
        tmp_path,
        scenes={"s-hook": fx.PURE_SCENE_PLAIN, "s-explain": fx.PURE_SCENE_PLAIN},
        lib={"count": _COUNT_GL_LIB},
    )
    page = await _open(browser, tmp_path)
    for t in (0.5, 3.5):
        await page.render_hash(t)
    assert await page.evaluate("window.__glContexts") == 0
    await page.close()
