"""Tests for scripts/tasks.py (the stdlib-only toolchain entry, ADR 0025).

The script lives outside the backend package, so it is loaded by path (same as
`test_check_docs_tech_debt.py`).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("tasks", REPO_ROOT / "scripts" / "tasks.py")
assert _spec is not None and _spec.loader is not None
tasks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tasks)


# ---- parse_dotenv ----


def test_parse_dotenv_supported_forms() -> None:
    text = "\n".join(
        [
            "# full-line comment",
            "",
            "   ",
            "PLAIN=value",
            "EMPTY=",
            "export EXPORTED=yes",
            "WITH_EQ=a=b==c",
            "SQ='single quoted # not a comment $NOT_EXPANDED'",
            'DQ="double quoted  with spaces"',
            "TRAILING=value # trailing comment",
            "HASH_NO_SPACE=a#b",
            "CONCAT='x'\"y\"z",
            'EMPTY_DQ=""',
            "  INDENTED=ok",
        ]
    )
    assert tasks.parse_dotenv(text) == {
        "PLAIN": "value",
        "EMPTY": "",
        "EXPORTED": "yes",
        "WITH_EQ": "a=b==c",
        "SQ": "single quoted # not a comment $NOT_EXPANDED",
        "DQ": "double quoted  with spaces",
        "TRAILING": "value",
        "HASH_NO_SPACE": "a#b",
        "CONCAT": "xyz",
        "EMPTY_DQ": "",
        "INDENTED": "ok",
    }


def test_parse_dotenv_later_assignment_wins() -> None:
    assert tasks.parse_dotenv("A=1\nA=2\n") == {"A": "2"}


def test_parse_dotenv_accepts_crlf() -> None:
    assert tasks.parse_dotenv("A=1\r\nB='x y'\r\n") == {"A": "1", "B": "x y"}


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("A=$HOME", 1),
        ("OK=1\nA=${HOME}/x", 2),
        ('A="pre $HOME"', 1),
        ("A=`whoami`", 1),
        ('A="$(whoami)"', 1),
        ("A=$(whoami)", 1),
        ("A=back\\slash", 1),
        ("A='unterminated", 1),
        ('A="unterminated', 1),
        ("A=two words", 1),
        ("NOT AN ASSIGNMENT", 1),
        ("1BAD=x", 1),
        ("A =x", 1),
    ],
)
def test_parse_dotenv_rejects_unsupported(text: str, line: int) -> None:
    with pytest.raises(ValueError, match=rf"第 {line} 行"):
        tasks.parse_dotenv(text)


DOTENV_FIXTURE = """\
# fixture compared against bash
PLAIN=value
export EXPORTED=yes
WITH_EQ=a=b==c
SQ='single # quoted $X'
DQ="double  spaced"
TRAILING=value # comment
HASH_NO_SPACE=a#b
CONCAT='x'"y"z
EMPTY=
"""


@pytest.mark.skipif(sys.platform == "win32", reason="比较对象是 POSIX 的 bash `set -a; . file`")
def test_parse_dotenv_matches_bash(tmp_path: Path) -> None:
    env_file = tmp_path / "fixture.env"
    env_file.write_text(DOTENV_FIXTURE, encoding="utf-8")
    parsed = tasks.parse_dotenv(DOTENV_FIXTURE)
    script = 'set -a; . "$1"; for k in "${@:2}"; do printf "%s\\0%s\\0" "$k" "${!k}"; done'
    out = subprocess.run(
        ["bash", "-c", script, "bash", str(env_file), *parsed],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    parts = out.split("\0")[:-1]
    from_bash = dict(zip(parts[::2], parts[1::2], strict=True))
    assert from_bash == parsed


# ---- smoke_env ----

_SMOKE_KEYS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY"]


def test_smoke_env_posix_whitelist() -> None:
    base = {
        "HOME": "/Users/me",
        "PATH": "/usr/bin",
        "USER": "me",
        "SHELL": "/bin/zsh",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "ANTHROPIC_BASE_URL": "http://proxy",
        "STUDIO_WEB_MODE": "off",
        "OPENAI_API_KEY": "from-env",
        "USERPROFILE": "C:\\Users\\me",
    }
    dotenv = {"ANTHROPIC_API_KEY": "from-dotenv", "OPENAI_API_KEY": "", "STUDIO_X": "1"}
    env = tasks.smoke_env(base, dotenv, _SMOKE_KEYS, "darwin")
    assert env == {
        "HOME": "/Users/me",
        "PATH": "/usr/bin",
        "USER": "me",
        "SHELL": "/bin/zsh",
        "LANG": "en_US.UTF-8",
        "TMPDIR": "/tmp",
        "ANTHROPIC_API_KEY": "from-dotenv",
        "STUDIO_WEB_MODE": "off",
        "STUDIO_X": "1",
    }


def test_smoke_env_dotenv_overrides_base() -> None:
    env = tasks.smoke_env(
        {"PATH": "/bin", "TAVILY_API_KEY": "old"}, {"TAVILY_API_KEY": "new"}, _SMOKE_KEYS, "linux"
    )
    assert env["TAVILY_API_KEY"] == "new"


def test_smoke_env_windows_whitelist() -> None:
    base = {
        "USERPROFILE": "C:\\Users\\me",
        "APPDATA": "C:\\Users\\me\\AppData\\Roaming",
        "LOCALAPPDATA": "C:\\Users\\me\\AppData\\Local",
        "PATH": "C:\\Windows",
        "SYSTEMROOT": "C:\\Windows",
        "TEMP": "C:\\Temp",
        "TMP": "C:\\Temp",
        "COMSPEC": "C:\\Windows\\system32\\cmd.exe",
        "PATHEXT": ".COM;.EXE",
        "HOME": "/should/not/leak",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "STUDIO_WEB_MODE": "off",
    }
    env = tasks.smoke_env(base, {"OPENAI_API_KEY": "k"}, _SMOKE_KEYS, "win32")
    expected = {k: v for k, v in base.items() if k not in ("HOME", "CLAUDE_CODE_ENTRYPOINT")}
    assert env == {**expected, "OPENAI_API_KEY": "k"}


def test_smoke_env_windows_lookup_is_case_insensitive() -> None:
    env = tasks.smoke_env({"Path": "C:\\Windows", "SystemRoot": "C:\\Windows"}, {}, [], "win32")
    assert env == {"PATH": "C:\\Windows", "SYSTEMROOT": "C:\\Windows"}


# ---- find_uv / find_pnpm ----


def _no_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks.shutil, "which", lambda *_a, **_k: None)


def test_find_uv_prefers_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks.shutil, "which", lambda name: f"/bin/{name}")
    assert tasks.find_uv() == "/bin/uv"


@pytest.mark.parametrize(
    ("platform", "rel"), [("darwin", ".local/bin/uv"), ("win32", ".local/bin/uv.exe")]
)
def test_find_uv_falls_back_to_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, rel: str
) -> None:
    _no_which(monkeypatch)
    exe = tmp_path / rel
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert tasks.find_uv(home=tmp_path, platform=platform) == str(exe)


def test_find_uv_missing_gives_install_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _no_which(monkeypatch)
    with pytest.raises(tasks.TaskError, match="uv"):
        tasks.find_uv(home=tmp_path, platform="darwin")


def test_find_pnpm_falls_back_to_nvm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _no_which(monkeypatch)
    for version in ("v20.1.0", "v22.3.0"):
        exe = tmp_path / ".nvm" / "versions" / "node" / version / "bin" / "pnpm"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
    found = tasks.find_pnpm(home=tmp_path, platform="darwin", environ={})
    assert found == str(tmp_path / ".nvm/versions/node/v22.3.0/bin/pnpm")


def test_find_pnpm_windows_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _no_which(monkeypatch)
    exe = tmp_path / "Roaming" / "npm" / "pnpm.cmd"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    environ = {"APPDATA": str(tmp_path / "Roaming")}
    assert tasks.find_pnpm(home=tmp_path, platform="win32", environ=environ) == str(exe)


def test_find_pnpm_missing_gives_install_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _no_which(monkeypatch)
    with pytest.raises(tasks.TaskError, match="pnpm"):
        tasks.find_pnpm(home=tmp_path, platform="win32", environ={})


# ---- step runner / CLI ----


def test_run_step_failure_names_the_step(tmp_path: Path) -> None:
    with pytest.raises(tasks.StepFailed) as info:
        tasks.run_step("boom", [sys.executable, "-c", "raise SystemExit(3)"], cwd=tmp_path)
    assert info.value.label == "boom"
    assert info.value.code == 3


def test_main_reports_failed_step(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_args: object) -> None:
        raise tasks.StepFailed("ruff check", 1)

    monkeypatch.setitem(tasks.COMMANDS, "check-docs", fail)
    assert tasks.main(["check-docs"]) == 1
    assert "ruff check" in capsys.readouterr().err


def test_cli_has_all_makefile_targets() -> None:
    assert set(tasks.COMMANDS) == {
        "setup",
        "check",
        "check-fast",
        "check-docs",
        "check-backend",
        "check-frontend",
        "smoke",
        "import-legacy-styles",
    }


def test_makefile_targets_are_thin_wrappers() -> None:
    """ADR 0025: every Makefile target delegates to tasks.py in a single line."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^TASKS := .*python scripts/tasks\.py$", makefile, re.M)
    for name in tasks.COMMANDS:
        recipe = re.search(rf"^{re.escape(name)}:\n((?:\t.*\n)+)", makefile, re.M)
        assert recipe is not None, name
        assert recipe.group(1).startswith(f"\t@$(TASKS) {name}"), name
        assert recipe.group(1).count("\n") == 1, name
