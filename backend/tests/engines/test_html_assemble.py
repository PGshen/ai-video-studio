"""`engines.render.html.assemble`：页面组装、路由表、哈希（设计 §5.1、§5.2）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from studio.engines.render.html.assemble import assemble, page_hash

TIMELINE: dict[str, Any] = {
    "duration": 3.0,
    "grid": None,
    "sections": [
        {"id": "s-hook", "label": "开场", "start": 0.0, "end": 1.5},
        {"id": "s-explain", "label": "讲解", "start": 1.5, "end": 3.0},
    ],
    "narration": [],
    "moments": [],
    "music": None,
    "lyrics": [],
}


def _write(workdir: Path, relpath: str, text: str) -> None:
    path = workdir / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(tmp_path: Path) -> Path:
    _write(tmp_path, "animation/scenes/s-hook.js", "module.exports = { draw() {} }; // HOOK\n")
    _write(
        tmp_path, "animation/scenes/s-explain.js", "module.exports = { draw() {} }; // EXPLAIN\n"
    )
    _write(tmp_path, "animation/lib/b.js", "const B = 2; // LIB-B\n")
    _write(tmp_path, "animation/lib/a.js", "const A = 1; // LIB-A\n")
    _write(tmp_path, "animation/global.js", "module.exports = { post() {} }; // GLOBAL\n")
    return tmp_path


def test_html_embeds_timeline_and_orders_scripts(tmp_path: Path) -> None:
    page = assemble(_project(tmp_path), TIMELINE)
    html = page.html
    match = re.search(r"window\.__TIMELINE__=(\{.*?\});window", html)
    assert match is not None
    assert json.loads(match.group(1))["sections"][1]["id"] == "s-explain"
    srcs = re.findall(r'<script src="scripts/([^"]+)"', html)
    assert srcs == [
        "animation/lib/a.js",
        "animation/lib/b.js",
        "animation/scenes/s-hook.js",
        "animation/scenes/s-explain.js",
        "animation/global.js",
        "studio-runtime.js",
    ]
    assert "window.renderAt" in page.scripts["studio-runtime.js"]


def test_scene_ids_with_hyphen_are_string_keys(tmp_path: Path) -> None:
    scripts = assemble(_project(tmp_path), TIMELINE).scripts
    assert '__SCENES__["s-hook"]' in scripts["animation/scenes/s-hook.js"]
    assert '__SCENES__["s-explain"]' in scripts["animation/scenes/s-explain.js"]
    assert "// HOOK" in scripts["animation/scenes/s-hook.js"]
    assert "// LIB-A" in scripts["animation/lib/a.js"]
    assert "// GLOBAL" in scripts["animation/global.js"]


def test_missing_scene_file_is_skipped_and_global_is_optional(tmp_path: Path) -> None:
    _write(tmp_path, "animation/scenes/s-hook.js", "module.exports = { draw() {} };\n")
    page = assemble(tmp_path, TIMELINE)
    assert "animation/scenes/s-hook.js" in page.scripts
    assert "animation/scenes/s-explain.js" not in page.scripts
    assert "animation/global.js" not in page.scripts


def test_scene_source_keeps_its_own_line_numbers(tmp_path: Path) -> None:
    _write(tmp_path, "animation/scenes/s-hook.js", "// line1\nmodule.exports = {};\n")
    wrapped = assemble(tmp_path, TIMELINE).scripts["animation/scenes/s-hook.js"]
    assert wrapped.splitlines()[0].endswith("// line1")


def test_script_close_tag_in_timeline_cannot_break_the_page(tmp_path: Path) -> None:
    timeline = json.loads(json.dumps(TIMELINE))
    timeline["sections"][0]["label"] = "</script><b>x"
    html = assemble(_project(tmp_path), timeline).html
    assert html.count("</script>") == html.count("<script")


def test_routes_cover_bundled_fonts_assets_and_style_fonts(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path, "animation/assets/logo.svg", "<svg/>")
    _write(tmp_path, "style/fonts/Brand.woff2", "x")
    page = assemble(tmp_path, TIMELINE)
    for key in (
        "fonts/anton.woff2",
        "fonts/spacemono.woff2",
        "fonts/spacemono-bold.woff2",
        "fonts/notosanssc-400.woff2",
        "fonts/notosanssc-700.woff2",
    ):
        assert page.routes[key].is_file()
    assert page.routes["assets/logo.svg"] == tmp_path / "animation" / "assets" / "logo.svg"
    assert page.routes["style-fonts/Brand.woff2"] == tmp_path / "style" / "fonts" / "Brand.woff2"
    assert "font-family:'Noto Sans SC'" in page.html
    assert "font-family:'Brand'" in page.html
    assert '["assets/logo.svg"]' in page.html


def test_routes_never_leave_the_workspace(tmp_path: Path) -> None:
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    work = tmp_path / "work"
    _write(work, "animation/scenes/s-hook.js", "module.exports = {};\n")
    (work / "animation" / "assets").mkdir(parents=True)
    (work / "animation" / "assets" / "link.png").symlink_to(outside)
    page = assemble(work, TIMELINE)
    assert "assets/link.png" not in page.routes
    for path in page.routes.values():
        assert path.resolve().is_relative_to(work.resolve()) or "fonts" in path.parts


def test_preview_script_only_when_requested(tmp_path: Path) -> None:
    _project(tmp_path)
    assert "__PREVIEW__" not in assemble(tmp_path, TIMELINE).html
    assert "__PREVIEW__" in assemble(tmp_path, TIMELINE, preview=True).html


def test_page_hash_reacts_to_every_input(tmp_path: Path) -> None:
    _project(tmp_path)
    base = page_hash(tmp_path, TIMELINE)
    assert page_hash(tmp_path, TIMELINE) == base
    changed = json.loads(json.dumps(TIMELINE))
    changed["duration"] = 3.5
    assert page_hash(tmp_path, changed) != base
    for relpath in (
        "animation/scenes/s-hook.js",
        "animation/lib/a.js",
        "animation/global.js",
    ):
        original = (tmp_path / relpath).read_text(encoding="utf-8")
        (tmp_path / relpath).write_text(original + "// edit\n", encoding="utf-8")
        assert page_hash(tmp_path, TIMELINE) != base
        (tmp_path / relpath).write_text(original, encoding="utf-8")
    _write(tmp_path, "animation/assets/x.svg", "<svg/>")
    assert page_hash(tmp_path, TIMELINE) != base


def test_html_comment_openers_in_timeline_text_cannot_break_the_page(tmp_path: Path) -> None:
    timeline = json.loads(json.dumps(TIMELINE))
    timeline["sections"][0]["label"] = "<!--<script>"
    html = assemble(_project(tmp_path), timeline).html
    head = html.split('<script src="scripts/')[0]
    assert "<!--" not in head


def test_style_font_names_with_quotes_cannot_break_the_css(tmp_path: Path) -> None:
    _write(tmp_path, "style/fonts/it's.woff2", "x")
    html = assemble(_project(tmp_path), TIMELINE).html
    assert "font-family:'it\\'s'" in html


# ---- serve_page_path：浏览器层与预览端点共用的路径查表 -------------------------------


def test_serve_page_path_returns_index_scripts_fonts_and_assets(tmp_path: Path) -> None:
    from studio.engines.render.html.assemble import serve_page_path

    workdir = _project(tmp_path)
    _write(workdir, "animation/assets/logo.svg", "<svg/>")
    page = assemble(workdir, TIMELINE)

    html = serve_page_path(page, "")
    assert html is not None and html.content_type.startswith("text/html")
    assert serve_page_path(page, "index.html") == html

    script = serve_page_path(page, "scripts/studio-runtime.js")
    assert script is not None and script.content_type.startswith("text/javascript")
    nested = serve_page_path(page, "scripts/animation/lib/a.js")
    assert nested is not None and b"LIB-A" in nested.body

    font = serve_page_path(page, "fonts/anton.woff2")
    assert font is not None and font.content_type == "font/woff2" and font.body[:4] == b"wOF2"
    asset = serve_page_path(page, "assets/logo.svg")
    assert asset is not None and asset.content_type == "image/svg+xml"


def test_serve_page_path_decodes_names_and_rejects_anything_not_in_the_page(
    tmp_path: Path,
) -> None:
    from studio.engines.render.html.assemble import serve_page_path

    workdir = _project(tmp_path)
    _write(workdir, "animation/assets/my logo.svg", "<svg/>")
    page = assemble(workdir, TIMELINE)

    assert serve_page_path(page, "assets/my%20logo.svg") is not None
    for bad in ("../x", "%2e%2e/x", "scripts/../../x", "/etc/passwd", "assets/nope.svg", "fonts/x"):
        assert serve_page_path(page, bad) is None, bad


# ---- inline=True：自包含页面（实时预览的 iframe 用 srcdoc，不依赖任何子资源请求）---------


def test_inline_page_has_no_external_references(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path, "style/fonts/Brand.woff2", "brand-font-bytes")
    html = assemble(tmp_path, TIMELINE, preview=True, inline=True).html
    assert "<script src=" not in html
    assert "url(fonts/" not in html and "url(style-fonts/" not in html
    assert html.count("data:font/woff2;base64,") == 6  # five bundled faces + one style font
    assert "window.renderAt" in html and "window.__PREVIEW__" in html


def test_inline_scripts_keep_their_file_names_for_error_reports(tmp_path: Path) -> None:
    html = assemble(_project(tmp_path), TIMELINE, inline=True).html
    for name in ("animation/lib/a.js", "animation/scenes/s-hook.js", "studio-runtime.js"):
        assert f"//# sourceURL={name}" in html
    assert html.index("// LIB-A") < html.index("// HOOK") < html.index("// GLOBAL")


def test_inline_script_text_cannot_close_the_script_tag(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "animation/scenes/s-hook.js",
        "module.exports = { draw() { return '</script><b>x</b>'; } };\n",
    )
    html = assemble(tmp_path, TIMELINE, inline=True).html
    assert html.count("</script>") == html.count("<script")


def test_inline_assets_are_data_uris_the_runtime_can_look_up_by_name(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path, "animation/assets/logo.svg", "<svg/>")
    page = assemble(tmp_path, TIMELINE, inline=True)
    match = re.search(r"window\.__ASSET_SRC__=(\{.*?\});", page.html)
    assert match is not None
    sources = json.loads(match.group(1))
    assert sources["logo.svg"].startswith("data:image/svg+xml;base64,")
    assert '["assets/logo.svg"]' in page.html


def test_non_inline_pages_are_unchanged(tmp_path: Path) -> None:
    html = assemble(_project(tmp_path), TIMELINE).html
    assert "__ASSET_SRC__" not in html and "data:font" not in html
