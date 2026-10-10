"""Cross-platform toolchain entry (ADR 0025): the single source of the Makefile logic.

Run from the repo root:

    uv run --project backend python scripts/tasks.py <command> [args...]

On macOS `make <command>` is a one-line wrapper around this; on Windows call it directly.
Stdlib only and never imports `studio`: it must work before `backend/.venv` is complete.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
FRONTEND = REPO_ROOT / "frontend"
PID_FILE = REPO_ROOT / ".dev" / "pids.json"
"""`dev`'s record of what it started; outside `data/` (uvicorn must not watch it)."""
FRONTEND_PORT = 5173

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


def utf8_env(base: Mapping[str, str]) -> dict[str, str]:
    """A copy of `base` with Python's UTF-8 mode on (design §7): the Windows default is the
    locale code page (GBK on a Chinese system). Mirrors `studio.proc.child_env`."""
    return {**base, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def run_step(
    label: str,
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> None:
    print(f"==> {label}", flush=True)
    child_env = utf8_env(os.environ if env is None else env)
    code = subprocess.run(list(argv), cwd=cwd, env=child_env).returncode
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
            ("ruff check", ["run", "ruff", "check", ".", "../scripts"]),
            ("ruff format --check", ["run", "ruff", "format", "--check", ".", "../scripts"]),
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
    _uv_steps([("ruff check", ["run", "ruff", "check", ".", "../scripts"])])
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


# ---- dev: api + worker + frontend (design §8.2) ----
#
# `_spawn_kwargs` and `_kill_tree_sync` are stdlib copies of `studio.proc.spawn_kwargs` /
# `kill_tree_sync` (backend/src/studio/proc.py): this script must not import `studio`.
# Change both together.

_CREATE_NEW_PROCESS_GROUP = 0x00000200
_WINDOWS_IMAGES = frozenset({"python.exe", "uv.exe", "node.exe", "cmd.exe"})
"""Images `dev` starts on Windows (`cmd.exe` runs `pnpm.CMD`); anything else is not ours."""


def _spawn_kwargs(platform: str | None = None) -> dict[str, Any]:
    if (platform or sys.platform) == "win32":
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree_sync(pid: int, platform: str | None = None) -> bool:
    if (platform or sys.platform) == "win32":
        try:
            done = subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            return False
        return done.returncode == 0
    if sys.platform != "win32":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)
    return True


def read_pid_file(path: Path) -> list[dict[str, Any]]:
    """Entries `{"name", "pid", "cmd"}`; a missing or malformed file is empty (best effort)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        entry
        for entry in data
        if isinstance(entry, dict)
        and isinstance(entry.get("name"), str)
        and isinstance(entry.get("pid"), int)
    ]


def write_pid_file(path: Path, entries: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(entries), ensure_ascii=False, indent=2), encoding="utf-8")


ProcessInfo = tuple[str, str]
"""`(image name, command line)` of a live process."""


def process_info(pid: int, platform: str | None = None) -> ProcessInfo | None:
    """Name and command line of `pid`, or `None` when it is gone (or cannot be inspected)."""
    if (platform or sys.platform) == "win32":
        # `tasklist` has no command line; CIM is the supported way (wmic is deprecated).
        script = (
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; "
            "if ($p) { $p.Name; $p.CommandLine }"
        )
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    else:
        argv = ["ps", "-o", "command=", "-p", str(pid)]
    try:
        done = subprocess.run(argv, capture_output=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = done.stdout.decode("utf-8", errors="replace").strip().splitlines()
    if done.returncode != 0 or not lines:
        return None
    if (platform or sys.platform) == "win32":
        return (lines[0].strip(), " ".join(lines[1:]).strip())
    command = lines[0].strip()
    return (Path(command.split(" ", 1)[0]).name, command)


def belongs_to_project(
    info: ProcessInfo | None, root: Path, *, platform: str | None = None
) -> bool:
    """Review point 2: a PID from the pid file may have been reused by another program, so
    only kill it when its command line names this repository (and, on Windows, its image is
    one `dev` starts). Paths compare case- and separator-insensitively on Windows."""
    if info is None:
        return False
    name, command = info
    if (platform or sys.platform) == "win32":
        if name.lower() not in _WINDOWS_IMAGES:
            return False
        return str(root).replace("/", "\\").lower() in command.replace("/", "\\").lower()
    return str(root) in command


def cleanup_stale(
    entries: Sequence[Mapping[str, Any]],
    root: Path,
    *,
    process_info: Callable[[int], ProcessInfo | None],
    kill: Callable[[int], object],
    log: IO[str],
    platform: str | None = None,
) -> None:
    """Kill what a previous `dev` left running, but only processes that are still ours."""
    for entry in entries:
        pid = int(entry["pid"])
        info = process_info(pid)
        if info is None:
            continue
        if belongs_to_project(info, root, platform=platform):
            print(f"清理上一次遗留的 {entry['name']}（pid {pid}）", file=log)
            kill(pid)
        else:
            print(f"pid {pid}（原来的 {entry['name']}）已被其他程序使用，跳过", file=log)


def parse_netstat_listeners(text: str, port: int) -> list[int]:
    """PIDs listening on TCP `port` in `netstat -ano` output (Windows)."""
    pids: list[int] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        if parts[1].rsplit(":", 1)[-1] == str(port):
            pid = int(parts[4])
            if pid not in pids:
                pids.append(pid)
    return pids


def port_listeners(port: int, platform: str | None = None) -> list[int]:
    if (platform or sys.platform) == "win32":
        argv = ["netstat", "-ano", "-p", "TCP"]
    else:
        argv = ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"]
    try:
        out = subprocess.run(argv, capture_output=True, check=False, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = out.decode("utf-8", errors="replace")
    if (platform or sys.platform) == "win32":
        return parse_netstat_listeners(text, port)
    return sorted({int(line) for line in text.split() if line.isdigit()})


@dataclass
class Service:
    name: str
    argv: list[str]
    cwd: Path


@dataclass
class Supervisor:
    """Starts services in their own process groups, prefixes their output, and kills every
    tree on `stop()`. stdin is always DEVNULL: a child that reads the terminal (ffmpeg does by
    default) would otherwise be stopped by SIGTTIN and freeze the API (lesson from dev.sh)."""

    services: Sequence[Service]
    env: Mapping[str, str] | None
    pid_file: Path
    out: IO[str] = field(default_factory=lambda: sys.stdout)
    started: list[dict[str, Any]] = field(default_factory=list)
    _procs: list[tuple[Service, subprocess.Popen[bytes]]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self) -> None:
        env = utf8_env(os.environ if self.env is None else self.env)
        for service in self.services:
            child = subprocess.Popen(
                service.argv,
                cwd=service.cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                **_spawn_kwargs(),
            )
            self._procs.append((service, child))
            self.started.append(
                {"name": service.name, "pid": child.pid, "cmd": " ".join(service.argv)}
            )
            threading.Thread(target=self._pump, args=(service.name, child), daemon=True).start()
        write_pid_file(self.pid_file, self.started)

    def _pump(self, name: str, child: subprocess.Popen[bytes]) -> None:
        assert child.stdout is not None
        for raw in iter(child.stdout.readline, b""):
            line = f"[{name}] " + raw.decode("utf-8", errors="replace").rstrip("\r\n")
            with self._lock:
                try:
                    print(line, file=self.out, flush=True)
                except UnicodeEncodeError:
                    # A GBK console cannot show e.g. Vite's `➜`; the thread must keep draining
                    # the pipe or the child blocks once it fills.
                    encoding = getattr(self.out, "encoding", None) or "ascii"
                    safe = line.encode(encoding, errors="replace").decode(encoding)
                    print(safe, file=self.out, flush=True)

    def wait(self, *, poll: float = 0.5) -> tuple[str, int]:
        """Block until a service exits; returns its name and exit code."""
        while True:
            for service, child in self._procs:
                code = child.poll()
                if code is not None:
                    return service.name, code
            time.sleep(poll)

    def stop(self) -> None:
        for _service, child in self._procs:
            # A child that already exited has no tree to find on Windows, and its PID may be
            # reused; POSIX still kills its group (leftovers keep the group alive).
            if child.poll() is None or sys.platform != "win32":
                if not _kill_tree_sync(child.pid) and child.poll() is None:
                    child.kill()
        for _service, child in self._procs:
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=10)
        self.pid_file.unlink(missing_ok=True)


def _interrupt(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def _bind_address(uv: str, env: Mapping[str, str]) -> tuple[str, str]:
    done = subprocess.run(
        [uv, "run", "--project", str(BACKEND), "python", "-m", "studio.config"],
        cwd=BACKEND,
        env=utf8_env(env),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    parts = done.stdout.decode("utf-8", errors="replace").split()
    if done.returncode != 0 or len(parts) != 2:
        sys.stderr.write(done.stderr.decode("utf-8", errors="replace"))
        raise TaskError("无法从 `python -m studio.config` 读取绑定地址，请检查上面的报错")
    return parts[0], parts[1]


def _require_free(port: int, label: str) -> None:
    owners = port_listeners(port)
    if owners:
        raise TaskError(
            f"端口 {port}（{label}）被 pid {', '.join(map(str, owners))} 占用，"
            "不是本项目上一次留下的进程；请手动结束它或修改端口配置"
        )


def cmd_dev(_args: argparse.Namespace) -> None:
    """Start api (uvicorn --reload), worker and the frontend; Ctrl+C stops all three."""
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, _interrupt)  # Ctrl+Break / closing the console window
    else:
        signal.signal(signal.SIGTERM, _interrupt)  # `kill <dev pid>` stops like Ctrl+C
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(line_buffering=True)  # keep progress visible when redirected
    cleanup_stale(
        read_pid_file(PID_FILE),
        REPO_ROOT,
        process_info=process_info,
        kill=_kill_tree_sync,
        log=sys.stdout,
    )
    PID_FILE.unlink(missing_ok=True)
    # Model keys are read from the process environment (pydantic-settings does not export
    # backend/.env), so `.env` is merged in here, as `set -a; . backend/.env` used to.
    env = {**os.environ, **load_dotenv()}
    uv, pnpm = find_uv(), find_pnpm()
    host, port = _bind_address(uv, env)
    env["STUDIO_BIND_PORT"] = port  # vite.config.ts proxies /api to it
    _require_free(int(port), "api")
    _require_free(FRONTEND_PORT, "frontend")
    project = ["--project", str(BACKEND)]  # absolute paths: `belongs_to_project` looks for them
    services = [
        # Only backend/src is watched: the workspace (data/) must never trigger a reload.
        Service(
            "api",
            [uv, "run", *project, "uvicorn", "studio.main:app", "--reload"]
            + ["--reload-dir", str(BACKEND / "src"), "--host", host, "--port", port],
            BACKEND,
        ),
        Service("worker", [uv, "run", *project, "python", "-m", "studio.worker"], BACKEND),
        Service("web", [pnpm, "--dir", str(FRONTEND), "run", "dev"], FRONTEND),
    ]
    supervisor = Supervisor(services, env=env, pid_file=PID_FILE)
    try:
        supervisor.start()
        print(f"api: http://{host}:{port}（OpenAPI：/docs）")
        print(f"frontend: http://127.0.0.1:{FRONTEND_PORT}")
        print("worker: 已启动；按 Ctrl+C 退出")
        name, code = supervisor.wait()
        raise TaskError(f"{name} 意外退出（退出码 {code}），其余进程已结束")
    except KeyboardInterrupt:
        print("\n正在结束 api、worker、frontend…")
    finally:
        supervisor.stop()


COMMANDS: dict[str, Callable[[argparse.Namespace], None]] = {
    "setup": cmd_setup,
    "check": cmd_check,
    "check-fast": cmd_check_fast,
    "check-docs": cmd_check_docs,
    "check-backend": cmd_check_backend,
    "check-frontend": cmd_check_frontend,
    "dev": cmd_dev,
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
            p.add_argument("rest", nargs="*", help="原样传给底层命令（可以以 - 开头）")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _PASSTHROUGH:
        # argparse cannot take a leading `-k ...` as positional input (REMAINDER in a
        # subcommand rejects it), so everything after the command name is passed on as is.
        args = argparse.Namespace(command=argv[0], rest=argv[1:])
    else:
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
