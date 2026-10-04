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
