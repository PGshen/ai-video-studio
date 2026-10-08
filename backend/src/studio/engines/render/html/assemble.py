"""把工作区和时间轴装配成可渲染的页面（设计 §5.1、§5.2）。

纯函数：不启动浏览器。`routes` 是 URL 相对路径到磁盘文件的映射，由浏览器层通过
`page.route` 供给；页面里所有文件引用都是相对路径。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from studio.engines.render.html.assets import escapes_workspace, list_assets

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
    scripts: dict[str, str]
    """生成的脚本文件（镜头包装、`lib`、`global`、运行时），页面用 `<script src>` 引用；
    作为独立文件加载，语法错误的报错里才会带文件名和正确的行号。"""


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _css_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _data_uri(path: Path, content_type: str) -> str:
    return f"data:{content_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _font_faces(style_fonts: list[Path], *, inline: bool) -> str:
    def source(route: str, path: Path) -> str:
        return _data_uri(path, "font/woff2") if inline else route

    rules = [
        f"@font-face{{font-family:'{family}';font-weight:{weight};"
        f"src:url({source(f'fonts/{name}', FONTS_DIR / name)}) format('woff2')}}"
        for family, weight, name in _BUNDLED_FACES
    ]
    rules += [
        f"@font-face{{font-family:'{_css_string(path.stem)}';"
        f"src:url({source(f'style-fonts/{quote(path.name)}', path)}) format('woff2')}}"
        for path in style_fonts
    ]
    return "".join(rules)


def _inline_script_text(source: str) -> str:
    """内联进 `<script>` 的 JS 文本不能提前结束脚本元素，也不能进入 HTML 注释状态。"""
    # HTML 分词器匹配结束标签不区分大小写（`</SCRIPT`、`</Script ` 同样会结束脚本）。
    return re.sub(r"</(script)", r"<\\/\1", source, flags=re.IGNORECASE).replace("<!--", "<\\!--")


def _inside(workdir: Path, paths: list[Path]) -> list[Path]:
    """Scripts whose real location is in the workspace: the render process runs outside the agent's
    sandbox, so a link to a file elsewhere must not be read (TD-69)."""
    return [p for p in paths if not escapes_workspace(p, workdir)]


def _style_fonts(workdir: Path) -> list[Path]:
    directory = workdir / "style" / "fonts"
    if not directory.is_dir():
        return []
    root = workdir.resolve()
    return sorted(
        p for p in directory.glob("*.woff2") if p.is_file() and p.resolve().is_relative_to(root)
    )


def assemble(
    workdir: Path,
    timeline: Mapping[str, Any],
    *,
    preview: bool = False,
    inline: bool = False,
    include_global: bool = True,
) -> AssembledPage:
    """`inline=True` 产出自包含页面：脚本内联（用 `//# sourceURL` 保留文件名）、字体和资产是
    data URI，页面不再发任何子资源请求。实时预览的 iframe 是不透明源的沙盒，浏览器可能不放行
    它对本机服务的请求，所以预览用 `srcdoc` 加载这种页面；成片和探测仍用路由表供给文件。

    `include_global=False` 不装配 `global.js`：短片的音乐平移检查要看镜头自己对节拍的响应，
    不能被全局后期（HUD 之类读节拍的效果）掩盖。"""
    animation = workdir / "animation"
    style_fonts = _style_fonts(workdir)
    assets = list_assets(workdir)

    routes: dict[str, Path] = {f"fonts/{name}": FONTS_DIR / name for _, _, name in _BUNDLED_FACES}
    routes.update({f"style-fonts/{p.name}": p for p in style_fonts})
    routes.update({f"assets/{p.name}": p for p in assets})

    scripts: dict[str, str] = {}

    def add_script(name: str, source: str) -> str:
        scripts[name] = source
        if inline:
            return f"<script>{_inline_script_text(source)}\n//# sourceURL={name}\n</script>"
        return f'<script src="scripts/{name}"></script>'

    parts = [
        '<!doctype html><meta charset="utf-8">',
        "<style>",
        _font_faces(style_fonts, inline=inline),
        "html,body{margin:0;background:#000}canvas{display:block}</style>",
        '<canvas id="c" width="1920" height="1080"></canvas>',
        # 第一段脚本先挂错误收集器：后面任何一段脚本的语法错误都会记进 __LOAD_ERRORS__。
        "<script>window.__LOAD_ERRORS__=[];window.addEventListener('error',function(e){"
        "window.__LOAD_ERRORS__.push("
        "String(e.message)+' ('+(e.filename||'')+':'+(e.lineno||0)+')')});</script>",
        f"<script>window.__TIMELINE__={_json_for_script(dict(timeline))};window.__SCENES__={{}};"
        f"window.__ASSETS__={_json_for_script([f'assets/{p.name}' for p in assets])};</script>",
    ]
    if inline:
        asset_sources = {p.name: _data_uri(p, _content_type(p)) for p in assets}
        parts.append(f"<script>window.__ASSET_SRC__={_json_for_script(asset_sources)};</script>")
    for lib in _inside(workdir, sorted((animation / "lib").glob("*.js"))):
        parts.append(add_script(f"animation/lib/{lib.name}", _read(lib)))
    for section in timeline.get("sections", []):
        scene = animation / "scenes" / f"{section['id']}.js"
        if scene.is_file() and not escapes_workspace(scene, workdir):
            wrapped = (
                "window.__SCENES__[" + json.dumps(section["id"]) + "]=(function(){"
                "const module={exports:{}};const exports=module.exports;"
                + _read(scene)
                + "\n;return module.exports;})();"
            )
            parts.append(add_script(f"animation/scenes/{scene.name}", wrapped))
    global_js = animation / "global.js"
    if include_global and global_js.is_file() and not escapes_workspace(global_js, workdir):
        wrapped = (
            "window.__GLOBAL__=(function(){const module={exports:{}};"
            "const exports=module.exports;"
            + _read(global_js)
            + "\n;return module.exports.post||module.exports;})();"
        )
        parts.append(add_script("animation/global.js", wrapped))
    parts.append(add_script("studio-runtime.js", _read(_RUNTIME)))
    if preview:
        parts.append(f"<script>{_PREVIEW_SCRIPT}</script>")
    return AssembledPage(html="".join(parts), routes=routes, scripts=scripts)


def page_hash(workdir: Path, timeline: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(dict(timeline), sort_keys=True, ensure_ascii=False).encode())
    animation = workdir / "animation"
    groups = [
        _inside(workdir, sorted((animation / "scenes").glob("*.js"))),
        _inside(workdir, sorted((animation / "lib").glob("*.js"))),
        _inside(workdir, [p for p in [animation / "global.js"] if p.is_file()]),
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


_CONTENT_TYPES: dict[str, str] = {
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


@dataclass(frozen=True, slots=True)
class ServedFile:
    body: bytes
    content_type: str


def serve_page_path(page: AssembledPage, path: str) -> ServedFile | None:
    """页面里一个相对 URL 路径对应的内容；不在页面里的一律返回 `None`（调用方回 404）。

    浏览器层（进程内 `page.route`）和预览端点（HTTP）共用这一处：路径先解码，再只在
    `AssembledPage` 的页面、脚本、路由表里查，永远不按路径去碰磁盘。
    """
    path = unquote(path.split("?", 1)[0])
    if path in ("", "index.html"):
        return ServedFile(page.html.encode("utf-8"), "text/html; charset=utf-8")
    if path.startswith("scripts/"):
        source = page.scripts.get(path[len("scripts/") :])
        if source is None:
            return None
        return ServedFile(source.encode("utf-8"), "text/javascript; charset=utf-8")
    file = page.routes.get(path)
    if file is None or not file.is_file():
        return None
    return ServedFile(file.read_bytes(), _content_type(file))
