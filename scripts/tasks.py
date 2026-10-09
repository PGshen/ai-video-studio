"""Cross-platform toolchain entry (ADR 0025): the single source of the Makefile logic.

Run from the repo root:

    uv run --project backend python scripts/tasks.py <command> [args...]

On macOS `make <command>` is a one-line wrapper around this; on Windows call it directly.
Stdlib only and never imports `studio`: it must work before `backend/.venv` is complete.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
FRONTEND = REPO_ROOT / "frontend"

# Keys the smoke tests read from the environment (moved from the Makefile).
SMOKE_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "VOLCENGINE_TTS_API_KEY",
    "TAVILY_API_KEY",
)

# Variables a process needs to run at all; everything else stays out of smoke runs so
# host-injected CLAUDE_CODE_* / ANTHROPIC_BASE_URL never reach the test cases (design §8.3).
_POSIX_BASE_KEYS = ("HOME", "PATH", "USER", "LANG", "TMPDIR", "SHELL")
_POSIX_DEFAULTS = {"LANG": "en_US.UTF-8", "TMPDIR": "/tmp", "SHELL": "/bin/bash"}
_WINDOWS_BASE_KEYS = (
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "COMSPEC",
    "PATHEXT",
)

DEFAULT_LEGACY_STYLES_FILE = REPO_ROOT / "data" / "legacy-export" / "styles.json"


class TaskError(Exception):
    """A precondition failed (missing tool, bad .env); the message is shown to the user."""


class StepFailed(Exception):
    """A step's command exited non-zero."""

    def __init__(self, label: str, code: int) -> None:
        super().__init__(f"{label}（退出码 {code}）")
        self.label = label
        self.code = code


# ---- locating tools ----


def _first_file(paths: Sequence[Path]) -> str | None:
    for path in paths:
        if path.is_file():
            return str(path)
    return None


def find_uv(*, home: Path | None = None, platform: str | None = None) -> str:
    """`uv` on PATH, else the installer's default location (Claude Code sandboxes may
    run with a PATH that lacks ~/.local/bin)."""
    found = shutil.which("uv")
    if found:
        return found
    home = home or Path.home()
    platform = platform or sys.platform
    exe = "uv.exe" if platform == "win32" else "uv"
    candidate = _first_file([home / ".local" / "bin" / exe, home / ".cargo" / "bin" / exe])
    if candidate:
        return candidate
    raise TaskError(
        "找不到 uv。安装：macOS 用 `curl -LsSf https://astral.sh/uv/install.sh | sh`，"
        "Windows 用 `winget install astral-sh.uv`；装完后新开终端。"
    )


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", path.name))


def find_pnpm(
    *,
    home: Path | None = None,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """`pnpm` on PATH (Windows resolves `pnpm.cmd` via PATHEXT), else common install spots."""
    found = shutil.which("pnpm")
    if found:
        return found
    home = home or Path.home()
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    candidates: list[Path] = []
    if platform == "win32":
        if environ.get("APPDATA"):
            candidates.append(Path(environ["APPDATA"]) / "npm" / "pnpm.cmd")
        if environ.get("LOCALAPPDATA"):
            candidates.append(Path(environ["LOCALAPPDATA"]) / "pnpm" / "pnpm.exe")
    else:
        node_dirs = sorted((home / ".nvm" / "versions" / "node").glob("*"), key=_version_key)
        candidates.extend(d / "bin" / "pnpm" for d in reversed(node_dirs))
        candidates.append(home / "Library" / "pnpm" / "pnpm")
        candidates.append(home / ".local" / "share" / "pnpm" / "pnpm")
    candidate = _first_file(candidates)
    if candidate:
        return candidate
    raise TaskError("找不到 pnpm。先装 Node 22+，再运行 `corepack enable`；装完后新开终端。")


# ---- backend/.env ----

_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _parse_value(raw: str, lineno: int) -> str:
    """The subset of shell word syntax `.env` may use; anything that would need a
    shell to evaluate (expansion, substitution, escapes) is rejected, never misread."""

    def bad(why: str) -> ValueError:
        return ValueError(f"backend/.env 第 {lineno} 行：{why}（tasks.py 只支持字面量的值）")

    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "'":
            end = raw.find("'", i + 1)
            if end < 0:
                raise bad("单引号没有闭合")
            out.append(raw[i + 1 : end])
            i = end + 1
        elif ch == '"':
            end = raw.find('"', i + 1)
            if end < 0:
                raise bad("双引号没有闭合")
            inner = raw[i + 1 : end]
            for special in ("$", "`", "\\"):
                if special in inner:
                    raise bad(f"双引号里不支持 `{special}`")
            out.append(inner)
            i = end + 1
        elif ch in " \t":
            rest = raw[i:].lstrip(" \t")
            if rest and not rest.startswith("#"):
                raise bad("值里有未加引号的空白")
            break
        elif ch in "$`\\":
            raise bad(f"不支持 `{ch}`")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `backend/.env` the way `set -a; . backend/.env` would, for a literal subset:
    `KEY=VALUE`, `export KEY=...`, single/double quotes, `#` comments, blank lines."""
    result: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        key, sep, raw = stripped.partition("=")
        if not sep or not _KEY_RE.fullmatch(key):
            raise ValueError(f"backend/.env 第 {lineno} 行：不是 KEY=VALUE 形式")
        result[key] = _parse_value(raw, lineno)
    return result


def load_dotenv(path: Path = BACKEND / ".env") -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        return parse_dotenv(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise TaskError(str(exc)) from exc


def smoke_env(
    base: Mapping[str, str],
    dotenv: Mapping[str, str],
    keys: Sequence[str],
    platform: str,
) -> dict[str, str]:
    """Whitelisted environment for `smoke` (the Python form of the old `env -i` + list).

    `.env` overrides the current environment (it used to be sourced on top of it);
    empty values are dropped like the old `[ -n "${!v:-}" ]` check.
    """
    windows = platform == "win32"
    # Windows env names are case-insensitive ("Path" vs "PATH").
    lookup = {k.upper(): v for k, v in base.items()} if windows else dict(base)
    env: dict[str, str] = {}
    if windows:
        for key in _WINDOWS_BASE_KEYS:
            if lookup.get(key):
                env[key] = lookup[key]
    else:
        for key in _POSIX_BASE_KEYS:
            value = lookup.get(key) or _POSIX_DEFAULTS.get(key)
            if value:
                env[key] = value
    merged = {**lookup, **dotenv}
    for key, value in merged.items():
        if value and (key in keys or key.startswith("STUDIO_")):
            env[key] = value
    return env


# ---- running steps ----


def run_step(
    label: str,
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> None:
    print(f"==> {label}", flush=True)
    code = subprocess.run(list(argv), cwd=cwd, env=None if env is None else dict(env)).returncode
    if code != 0:
        raise StepFailed(label, code)


def _uv_steps(steps: Sequence[tuple[str, Sequence[str]]]) -> None:
    uv = find_uv()
    for label, argv in steps:
        run_step(label, [uv, *argv], cwd=BACKEND)


def _pnpm_steps(steps: Sequence[tuple[str, Sequence[str]]]) -> None:
    pnpm = find_pnpm()
    for label, argv in steps:
        run_step(label, [pnpm, *argv], cwd=FRONTEND)


def cmd_setup(_args: argparse.Namespace) -> None:
    run_step("git hooks", ["git", "config", "core.hooksPath", ".githooks"], cwd=REPO_ROOT)
    _uv_steps(
        [
            ("uv sync", ["sync"]),
            ("playwright install chromium", ["run", "playwright", "install", "chromium"]),
        ]
    )
    _pnpm_steps([("pnpm install", ["install"])])


def cmd_check_docs(_args: argparse.Namespace) -> None:
    run_step("check_docs", [sys.executable, "scripts/check_docs.py"], cwd=REPO_ROOT)


def cmd_check_backend(_args: argparse.Namespace) -> None:
    _uv_steps(
        [
            ("ruff check", ["run", "ruff", "check", "."]),
            ("ruff format --check", ["run", "ruff", "format", "--check", "."]),
            ("pyright", ["run", "pyright"]),
            ("lint-imports", ["run", "lint-imports"]),
            ("pytest", ["run", "pytest"]),
        ]
    )


def cmd_check_frontend(_args: argparse.Namespace) -> None:
    _pnpm_steps(
        [
            ("frontend lint", ["run", "lint"]),
            ("frontend typecheck", ["run", "typecheck"]),
            ("vitest", ["exec", "vitest", "run"]),
        ]
    )


def cmd_check(args: argparse.Namespace) -> None:
    cmd_check_docs(args)
    cmd_check_backend(args)
    cmd_check_frontend(args)
    print("check 全部通过")


def cmd_check_fast(args: argparse.Namespace) -> None:
    """The subset pre-commit runs."""
    cmd_check_docs(args)
    _uv_steps([("ruff check", ["run", "ruff", "check", "."])])
    _pnpm_steps([("frontend lint", ["run", "lint"])])


def cmd_smoke(args: argparse.Namespace) -> None:
    """Real-model smoke tests with only whitelisted variables (not part of `check`)."""
    env = smoke_env(os.environ, load_dotenv(), SMOKE_KEYS, sys.platform)
    print(f"smoke: 只带白名单变量（{len(env)} 个）")
    run_step(
        "pytest -m smoke",
        [find_uv(), "run", "pytest", "-m", "smoke", "-v", "-rs", *args.rest],
        cwd=BACKEND,
        env=env,
    )


def cmd_import_legacy_styles(args: argparse.Namespace) -> None:
    """One-off import of the legacy style library (export side stays bash-only, ADR 0025)."""
    rest = list(args.rest)
    source = DEFAULT_LEGACY_STYLES_FILE
    if rest and not rest[0].startswith("-"):
        source = Path(rest.pop(0))
    _uv_steps(
        [
            (
                "import legacy styles",
                ["run", "python", "-m", "studio.db.legacy_styles", "import"]
                + [str(source.resolve()), *rest],
            )
        ]
    )


COMMANDS: dict[str, Callable[[argparse.Namespace], None]] = {
    "setup": cmd_setup,
    "check": cmd_check,
    "check-fast": cmd_check_fast,
    "check-docs": cmd_check_docs,
    "check-backend": cmd_check_backend,
    "check-frontend": cmd_check_frontend,
    "smoke": cmd_smoke,
    "import-legacy-styles": cmd_import_legacy_styles,
}

_PASSTHROUGH = {"smoke", "import-legacy-styles"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tasks.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in COMMANDS.items():
        doc_lines = (func.__doc__ or "").strip().splitlines()
        p = sub.add_parser(name, help=doc_lines[0] if doc_lines else None)
        if name in _PASSTHROUGH:
            p.add_argument("rest", nargs=argparse.REMAINDER, help="原样传给底层命令")
    args = parser.parse_args(argv)
    try:
        COMMANDS[args.command](args)
    except StepFailed as exc:
        print(f"tasks.py {args.command} 失败：{exc}", file=sys.stderr)
        return exc.code or 1
    except TaskError as exc:
        print(f"tasks.py {args.command}：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
