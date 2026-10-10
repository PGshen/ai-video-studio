"""Guards for lint rules that replaced written conventions (SOP §10).

Removing a rule from `pyproject.toml` would silently drop the check, so these tests feed
ruff a violating snippet under the project configuration and expect it to be reported.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent


def _ruff_codes(source: str, filename: Path) -> str:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--output-format",
            "concise",
            "--stdin-filename",
            str(filename),
            "-",
        ],
        input=source.encode("utf-8"),
        cwd=BACKEND,
        capture_output=True,
        check=False,
    )
    return result.stdout.decode("utf-8", errors="replace")


@pytest.mark.parametrize(
    "snippet",
    [
        'open("notes.md")\n',
        'from pathlib import Path\n\nPath("a.json").read_text()\n',
        'from pathlib import Path\n\nPath("a.json").write_text("x")\n',
    ],
)
def test_text_io_without_encoding_is_reported(snippet: str) -> None:
    """Design §7: text IO always names UTF-8 (Windows defaults to the locale code page)."""
    out = _ruff_codes(snippet, BACKEND / "src" / "studio" / "_lint_probe.py")
    assert "unspecified-encoding" in out, out


def test_explicit_encoding_passes() -> None:
    out = _ruff_codes('open("notes.md", encoding="utf-8")\n', BACKEND / "src" / "studio" / "_p.py")
    assert "unspecified-encoding" not in out, out


def test_scripts_are_checked_too() -> None:
    """`scripts/*.py` (stdlib toolchain) follow the same rule (ADR 0025, plan T2)."""
    out = _ruff_codes('open("notes.md")\n', REPO_ROOT / "scripts" / "_lint_probe.py")
    assert "unspecified-encoding" in out, out


# ---- what PLW1514 cannot see ----
#
# ruff only flags `read_text`/`write_text` on values it can type as `Path`; `(dir / "x")`
# or a `Path` parameter slips through. Method calls of these shapes are what pathlib
# offers, so the AST check below covers them for production code and scripts. Tests run
# in UTF-8 mode instead (`tasks.py` sets PYTHONUTF8, see conftest), so they are not scanned.


def _unspecified_encoding_calls(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if any(kw.arg == "encoding" for kw in node.keywords):
            continue
        name, positional = node.func.attr, len(node.args)
        if (name == "read_text" and positional == 0) or (name == "write_text" and positional == 1):
            lines.append(node.lineno)
    return lines


def test_the_ast_check_catches_what_ruff_misses() -> None:
    tree = ast.parse(
        "def f(d):\n"
        "    (d / 'a').read_text()\n"
        "    d.write_text('x')\n"
        "    d.read_text(encoding='utf-8')\n"
        "    files.read_text(d, 'a.md')\n"
        "    files.write_text(d, 'a.md', 'x', scope)\n"
    )
    assert _unspecified_encoding_calls(tree) == [2, 3]


def test_production_code_names_the_encoding_for_text_io() -> None:
    sources = [
        *sorted((BACKEND / "src").rglob("*.py")),
        *sorted((REPO_ROOT / "scripts").glob("*.py")),
    ]
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"
        for path in sources
        for line in _unspecified_encoding_calls(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert offenders == []


def test_windows_without_utf8_mode_is_refused_with_a_hint() -> None:
    from conftest import utf8_mode_problem

    assert utf8_mode_problem("win32", 0) is not None
    assert "tasks.py" in (utf8_mode_problem("win32", 0) or "")
    assert utf8_mode_problem("win32", 1) is None
    assert utf8_mode_problem("darwin", 0) is None


# ---- text writes keep "\n" as is (windows-native T9) ----
#
# Text mode turns "\n" into "\r\n" on Windows, so the same agent edit would store different
# bytes (and snapshot hashes) than on macOS. Production code writes text with `newline=""`.


def _translating_writes(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or any(kw.arg == "newline" for kw in node.keywords):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "write_text" and len(node.args) == 1:
            lines.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id == "open":
            mode = node.args[1] if len(node.args) > 1 else None
            mode = mode or next((kw.value for kw in node.keywords if kw.arg == "mode"), None)
            if (
                isinstance(mode, ast.Constant)
                and isinstance(mode.value, str)
                and set(mode.value) & {"w", "a", "x"}
                and "b" not in mode.value
            ):
                lines.append(node.lineno)
    return lines


def test_the_newline_check_catches_translating_writes() -> None:
    tree = ast.parse(
        "def f(p):\n"
        "    p.write_text('x', encoding='utf-8')\n"
        "    p.write_text('x', encoding='utf-8', newline='')\n"
        "    open(p, 'w', encoding='utf-8')\n"
        "    open(p, 'wb')\n"
        "    open(p, encoding='utf-8')\n"
        "    files.write_text(d, 'a.md', 'x', scope)\n"
    )
    assert _translating_writes(tree) == [2, 4]


def test_production_text_writes_keep_newlines() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"
        for path in sorted((BACKEND / "src").rglob("*.py"))
        for line in _translating_writes(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert offenders == []


# ---- child processes go through `studio.proc` (windows-native T4) ----
#
# Without `spawn_kwargs()` a child shares our process group (POSIX) or console group
# (Windows), so `kill_tree` cannot reach its descendants and a console Ctrl+C hits it too.
# `studio/proc.py` is the one place allowed to spawn without it.

_SPAWNERS = {
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
    "subprocess": {"Popen", "run", "call", "check_call", "check_output"},
}


def _passes_spawn_kwargs(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg is None and isinstance(kw.value, ast.Call):
            func = kw.value.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "spawn_kwargs":
                return True
    return False


def _spawns_without_proc(tree: ast.AST) -> list[int]:
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.attr in _SPAWNERS.get(node.func.value.id, ())
        and not _passes_spawn_kwargs(node)
    )


def test_the_spawn_check_catches_bare_child_processes() -> None:
    tree = ast.parse(
        "async def f(argv):\n"
        "    await asyncio.create_subprocess_exec(*argv)\n"
        "    await asyncio.create_subprocess_exec(*argv, **proc.spawn_kwargs())\n"
        "    subprocess.Popen(argv, env=env)\n"
        "    subprocess.run(argv, **spawn_kwargs())\n"
        "    runner.run(job)\n"
        "    asyncio.run(main())\n"
    )
    assert _spawns_without_proc(tree) == [2, 4]


def test_production_child_processes_use_spawn_kwargs() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"
        for path in sorted((BACKEND / "src").rglob("*.py"))
        if path.name != "proc.py" or path.parent.name != "studio"
        for line in _spawns_without_proc(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert offenders == []
