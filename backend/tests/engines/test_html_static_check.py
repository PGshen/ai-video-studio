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


# ---- 字面量时刻：lt 与数字字面量比较（子项目 3 设计 §6.3） ----


@pytest.mark.parametrize(
    "code",
    [
        "if (lt > 3.5) draw();",
        "if (lt >= 2) draw();",
        "const on = lt < 0.75;",
        "if (3.5 < lt) draw();",
        "if (env.t > 8.2) draw();",
        "const a = lt<=1.5 ? 1 : 0;",
    ],
)
def test_comparing_the_time_with_a_literal_second_is_a_warning(tmp_path: Path, code: str) -> None:
    from studio.engines.render.html.static_check import literal_time_warnings

    _write(
        tmp_path,
        "animation/scenes/s1.js",
        f"module.exports = {{ draw(ctx, lt, env) {{ {code} }} }};\n",
    )
    warnings = literal_time_warnings(tmp_path)
    assert len(warnings) == 1
    assert warnings[0].path == "animation/scenes/s1.js" and warnings[0].line == 1
    assert "env" in warnings[0].message


@pytest.mark.parametrize(
    "code",
    [
        "if (lt > 0) draw();",  # zero is "has started", not a time
        "if (lt < env.bt(2)) draw();",
        "if (lt > t0 + 0.5) draw();",
        "const x = 2.5 * lt;",
        "// if (lt > 3.5) draw();",
        "const n = ctlt > 4;",
        "if (lt > 3.5px) {}".replace("3.5px", "env.cue(0)"),
    ],
)
def test_other_expressions_do_not_warn(tmp_path: Path, code: str) -> None:
    from studio.engines.render.html.static_check import literal_time_warnings

    _write(
        tmp_path,
        "animation/scenes/s1.js",
        f"module.exports = {{ draw(ctx, lt, env) {{\n{code}\n}} }};\n",
    )
    assert literal_time_warnings(tmp_path) == []


def test_literal_time_warnings_cover_lib_and_global(tmp_path: Path) -> None:
    from studio.engines.render.html.static_check import literal_time_warnings

    _write(tmp_path, "animation/lib/k.js", "function f(lt) { return lt > 4.5 ? 1 : 0; }\n")
    _write(
        tmp_path,
        "animation/global.js",
        "module.exports = { post(ctx, t, env) { if (env.t > 6) {} } };\n",
    )
    paths = {w.path for w in literal_time_warnings(tmp_path)}
    assert paths == {"animation/lib/k.js", "animation/global.js"}


class TestScriptsOutsideTheWorkspace:
    """TD-69: a scene/lib/global script linking outside the workspace is neither read nor used."""

    def _outside(self, tmp_path: Path) -> Path:
        outside = tmp_path / "outside" / "secret.js"
        outside.parent.mkdir()
        outside.write_text("const leaked = Math.random();\n", encoding="utf-8")
        return outside

    @pytest.mark.parametrize(
        "relpath",
        ["animation/scenes/s-a.js", "animation/lib/x.js", "animation/global.js"],
    )
    def test_a_link_to_the_outside_is_reported_and_not_scanned(
        self, tmp_path: Path, relpath: str
    ) -> None:
        workdir = tmp_path / "work"
        link = workdir / relpath
        link.parent.mkdir(parents=True)
        link.symlink_to(self._outside(tmp_path))

        issues = static_check(workdir)

        assert [(i.path, i.line) for i in issues] == [(relpath, 0)]
        assert "工作区外" in issues[0].message

    def test_a_link_that_stays_inside_the_workspace_is_scanned_normally(
        self, tmp_path: Path
    ) -> None:
        workdir = tmp_path / "work"
        _write(workdir, "animation/lib/real.js", "const d = new Date();\n")
        (workdir / "animation/scenes").mkdir(parents=True)
        (workdir / "animation/scenes/s-a.js").symlink_to(workdir / "animation/lib/real.js")

        assert {i.path for i in static_check(workdir)} == {
            "animation/lib/real.js",
            "animation/scenes/s-a.js",
        }
