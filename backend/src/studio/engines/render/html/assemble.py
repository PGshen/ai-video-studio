"""把工作区和时间轴装配成可渲染的页面（设计 §5.1、§5.2）。

纯函数：不启动浏览器。`routes` 是 URL 相对路径到磁盘文件的映射，由浏览器层通过
`page.route` 供给；页面里所有文件引用都是相对路径。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio.engines.render.html.assets import list_assets

_PACKAGE = Path(__file__).parent
FONTS_DIR = _PACKAGE / "fonts"
_RUNTIME = _PACKAGE / "runtime.js"

_BUNDLED_FACES = [
    ("Anton", 400, "anton.woff2"),
    ("Space Mono", 400, "spacemono.woff2"),
    ("Space Mono", 700, "spacemono-bold.woff2"),
    ("Noto Sans SC", 400, "notosanssc-400.woff2"),
    ("Noto Sans SC", 700, "notosanssc-700.woff2"),
]

_PREVIEW_SCRIPT = """
window.__PREVIEW__ = true;
(function () {
  var pending = null;
  window.addEventListener('message', function (e) {
    var m = e.data;
    if (!m || m.type !== 'seek') return;
    if (pending !== null) cancelAnimationFrame(pending);
    pending = requestAnimationFrame(function () {
      pending = null;
      try { window.renderAt(m.t); }
      catch (err) {
        parent.postMessage({type: 'error', message: String(err && err.message || err)}, '*');
      }
    });
  });
  window.ready.then(function () {
    parent.postMessage({type: 'ready', duration: window.__TIMELINE__.duration}, '*');
  }, function (err) {
    parent.postMessage({type: 'error', message: String(err && err.message || err)}, '*');
  });
})();
"""


@dataclass(frozen=True, slots=True)
class AssembledPage:
    html: str
    routes: dict[str, Path]


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _source_for_script(source: str) -> str:
    return source.replace("</script", "<\\/script")


def _script(source: str, name: str) -> str:
    return f"<script>{_source_for_script(source)}\n//# sourceURL={name}\n</script>"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _font_faces(style_fonts: list[Path]) -> str:
    rules = [
        f"@font-face{{font-family:'{family}';font-weight:{weight};"
        f"src:url(fonts/{name}) format('woff2')}}"
        for family, weight, name in _BUNDLED_FACES
    ]
    rules += [
        f"@font-face{{font-family:'{path.stem}';src:url(style-fonts/{path.name}) format('woff2')}}"
        for path in style_fonts
    ]
    return "".join(rules)


def _style_fonts(workdir: Path) -> list[Path]:
    directory = workdir / "style" / "fonts"
    if not directory.is_dir():
        return []
    root = workdir.resolve()
    return sorted(
        p for p in directory.glob("*.woff2") if p.is_file() and p.resolve().is_relative_to(root)
    )


def assemble(workdir: Path, timeline: Mapping[str, Any], *, preview: bool = False) -> AssembledPage:
    animation = workdir / "animation"
    style_fonts = _style_fonts(workdir)
    assets = list_assets(workdir)

    routes: dict[str, Path] = {f"fonts/{name}": FONTS_DIR / name for _, _, name in _BUNDLED_FACES}
    routes.update({f"style-fonts/{p.name}": p for p in style_fonts})
    routes.update({f"assets/{p.name}": p for p in assets})

    parts = [
        '<!doctype html><meta charset="utf-8">',
        "<style>",
        _font_faces(style_fonts),
        "html,body{margin:0;background:#000}canvas{display:block}</style>",
        '<canvas id="c" width="1920" height="1080"></canvas>',
        # 第一段脚本先挂错误收集器：后面任何一段脚本的语法错误都会记进 __LOAD_ERRORS__。
        "<script>window.__LOAD_ERRORS__=[];window.addEventListener('error',function(e){"
        "window.__LOAD_ERRORS__.push("
        "String(e.message)+' ('+(e.filename||'')+':'+(e.lineno||0)+')')});</script>",
        f"<script>window.__TIMELINE__={_json_for_script(dict(timeline))};window.__SCENES__={{}};"
        f"window.__ASSETS__={_json_for_script([f'assets/{p.name}' for p in assets])};</script>",
    ]
    for lib in sorted((animation / "lib").glob("*.js")):
        parts.append(_script(_read(lib), f"animation/lib/{lib.name}"))
    for section in timeline.get("sections", []):
        scene = animation / "scenes" / f"{section['id']}.js"
        if scene.is_file():
            wrapped = (
                "window.__SCENES__[" + json.dumps(section["id"]) + "]=(function(){"
                "const module={exports:{}};const exports=module.exports;\n"
                + _read(scene)
                + "\n;return module.exports;})();"
            )
            parts.append(_script(wrapped, f"animation/scenes/{scene.name}"))
    global_js = animation / "global.js"
    if global_js.is_file():
        wrapped = (
            "window.__GLOBAL__=(function(){const module={exports:{}};"
            "const exports=module.exports;\n"
            + _read(global_js)
            + "\n;return module.exports.post||module.exports;})();"
        )
        parts.append(_script(wrapped, "animation/global.js"))
    parts.append(_script(_read(_RUNTIME), "studio-runtime.js"))
    if preview:
        parts.append(f"<script>{_PREVIEW_SCRIPT}</script>")
    return AssembledPage(html="".join(parts), routes=routes)


def page_hash(workdir: Path, timeline: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(dict(timeline), sort_keys=True, ensure_ascii=False).encode())
    animation = workdir / "animation"
    groups = [
        sorted((animation / "scenes").glob("*.js")),
        sorted((animation / "lib").glob("*.js")),
        [p for p in [animation / "global.js"] if p.is_file()],
        list_assets(workdir),
        _style_fonts(workdir),
        [_RUNTIME],
    ]
    for group in groups:
        for path in group:
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        digest.update(b"|")
    return digest.hexdigest()
