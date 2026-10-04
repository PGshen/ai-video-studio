"""`engines.render.html.static_check`：确定性静态检查与字号警告（设计 §6.3）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from studio.engines.render.html.static_check import font_size_warnings, static_check


def _write(workdir: Path, relpath: str, text: str) -> None:
    path = workdir / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("code", "keyword"),
    [
        ("const r = Math.random();", "Math.random"),
        ("const d = new Date();", "Date"),
        ("const n = performance.now();", "performance.now"),
        ("requestAnimationFrame(loop);", "requestAnimationFrame"),
        ("setTimeout(f, 10);", "setTimeout"),
        ("setInterval(f, 10);", "setInterval"),
        ("fetch('a.json');", "fetch"),
        ("new XMLHttpRequest();", "XMLHttpRequest"),
        ("const u = 'https://example.com/x.png';", "URL"),
        ('const u = "http://example.com";', "URL"),
        ("eval('1+1');", "eval"),
        ("const f = new Function('return 1');", "Function"),
    ],
)
def test_forbidden_api_is_reported_with_line(tmp_path: Path, code: str, keyword: str) -> None:
    _write(tmp_path, "animation/scenes/s-hook.js", f"// header\n{code}\n")
    issues = static_check(tmp_path)
    assert len(issues) == 1
    assert issues[0].path == "animation/scenes/s-hook.js"
    assert issues[0].line == 2
    assert keyword in issues[0].message


def test_comments_are_ignored(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "animation/scenes/s-a.js",
        "// Math.random() is forbidden\n/* new Date()\n   fetch(x) */\n"
        "const ok = 1; // setTimeout\n",
    )
    assert static_check(tmp_path) == []


def test_line_numbers_survive_block_comments(tmp_path: Path) -> None:
    _write(tmp_path, "animation/scenes/s-a.js", "/*\n\n*/\nMath.random();\n")
    assert static_check(tmp_path)[0].line == 4


def test_comment_marker_inside_string_does_not_hide_code(tmp_path: Path) -> None:
    _write(tmp_path, "animation/scenes/s-a.js", "const a = '//'; Math.random();\n")
    assert len(static_check(tmp_path)) == 1


def test_identifier_containing_forbidden_word_is_not_reported(tmp_path: Path) -> None:
    _write(tmp_path, "animation/scenes/s-a.js", "const updateDate = 1; const myfetch = 2;\n")
    assert static_check(tmp_path) == []


def test_lib_and_global_are_scanned_too(tmp_path: Path) -> None:
    _write(tmp_path, "animation/lib/util.js", "Math.random();\n")
    _write(tmp_path, "animation/global.js", "Date.now();\n")
    paths = {issue.path for issue in static_check(tmp_path)}
    assert paths == {"animation/lib/util.js", "animation/global.js"}


def test_clean_workspace_and_missing_dirs(tmp_path: Path) -> None:
    assert static_check(tmp_path) == []


def test_small_literal_font_sizes_warn(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "animation/scenes/s-a.js",
        "ctx.font = '700 12px Anton';\nctx.font = `40px 'Noto Sans SC'`;\nctx.font = '23.5px x';\n",
    )
    warnings = font_size_warnings(tmp_path)
    assert [w.line for w in warnings] == [1, 3]
    assert "24" in warnings[0].message


def test_font_warning_ignores_non_font_lines(tmp_path: Path) -> None:
    _write(tmp_path, "animation/scenes/s-a.js", "const w = 12 + 'px';\nconst x = '10px';\n")
    assert font_size_warnings(tmp_path) == []
