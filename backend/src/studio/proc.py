"""Controlled subprocesses on both platforms (windows-native design §6).

One place for "start a child we may have to kill, then kill its whole tree": POSIX puts the
child in a new session and kills the process group; Windows starts a new process group and
uses the system `taskkill /T /F` (no new dependency). `child_env` turns on Python's UTF-8 mode
for every child (design §7).

`scripts/tasks.py` keeps a stdlib-only copy of `spawn_kwargs` / `kill_tree_sync` / `child_env`
(`utf8_env`) because it must not import `studio`; change both together.

This module imports nothing from `studio` (import-linter contract).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Mapping
from typing import Any, Protocol

_CREATE_NEW_PROCESS_GROUP = 0x00000200
"""`subprocess.CREATE_NEW_PROCESS_GROUP`, spelled out because the constant only exists on
Windows."""

WINDOWS_RUNTIME_ENV = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")
"""Variables Windows programs need just to start (Python dies without SYSTEMROOT). They hold
no secrets, so whitelisted child environments always get them."""


class ProcessLike(Protocol):
    """What `kill_tree` needs from `asyncio.subprocess.Process` (fakes in tests match it)."""

    @property
    def pid(self) -> int: ...

    @property
    def returncode(self) -> int | None: ...

    def kill(self) -> None: ...


def _platform(platform: str | None) -> str:
    return platform or sys.platform


def spawn_kwargs(platform: str | None = None) -> dict[str, Any]:
    """Keyword arguments for `create_subprocess_exec` / `Popen` so `kill_tree` can reach the
    child's descendants: a new session (POSIX) or a new process group (Windows)."""
    if _platform(platform) == "win32":
        return {"creationflags": _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def child_env(
    base: Mapping[str, str],
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """A copy of `base` for a child process: UTF-8 mode on, and on Windows the variables a
    program needs to start (`WINDOWS_RUNTIME_ENV`, from `environ`) unless `base` sets them."""
    env = dict(base)
    if _platform(platform) == "win32":
        source = os.environ if environ is None else environ
        for key in WINDOWS_RUNTIME_ENV:
            if key not in env and key in source:
                env[key] = source[key]
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return env


def _killpg(pid: int) -> None:
    if sys.platform == "win32":
        raise OSError("process groups are POSIX-only")
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def kill_tree_sync(pid: int, *, platform: str | None = None) -> bool:
    """Kill `pid` and its descendants; `False` when Windows `taskkill` did not succeed.

    POSIX kills the process group `pid` leads (started with `spawn_kwargs`); a group that is
    already gone counts as success. The caller must know `pid` is still the child it started.
    """
    if _platform(platform) != "win32":
        _killpg(pid)
        return True
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


def _windows_may_target(process: ProcessLike) -> bool:
    # Once a child has exited its PID may be reused, and `taskkill /T` would then kill some
    # other process's tree. Descendants of an exited parent cannot be found by `/T` anyway.
    return process.returncode is None


def kill_proc_tree(process: ProcessLike, *, platform: str | None = None) -> None:
    """Synchronous `kill_tree`, for callbacks that cannot await (it blocks briefly on Windows)."""
    if _platform(platform) == "win32":
        if _windows_may_target(process) and not kill_tree_sync(process.pid, platform="win32"):
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        return
    kill_tree_sync(process.pid, platform=platform)


def run_killing_tree(
    argv: list[str],
    *,
    timeout: float,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """`subprocess.run(argv, capture_output=True, timeout=...)` for blocking callers, except
    that a timeout kills the whole tree (plain `run` kills only the direct child). stdin is
    `DEVNULL`; the child gets `child_env(env or os.environ)`. Raises `TimeoutExpired`."""
    group = spawn_kwargs()  # spelled out below: `**` would hide the bytes overload of Popen
    with subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env(os.environ if env is None else env),
        start_new_session=group.get("start_new_session", False),
        creationflags=group.get("creationflags", 0),
    ) as child:
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_proc_tree(child)
            child.communicate()
            raise
        return subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)


async def kill_tree(process: ProcessLike, *, platform: str | None = None) -> None:
    """Kill a child started with `spawn_kwargs` together with everything it started.

    POSIX: `killpg(SIGKILL)` on its group, also after it exited (cleans up leftovers that
    kept the group). Windows: `taskkill /T /F` while it is still running, falling back to
    `process.kill()`; after it exited nothing can be targeted safely (tech debt: Job Objects).
    """
    if _platform(platform) != "win32":
        kill_tree_sync(process.pid, platform=platform)
        return
    if not _windows_may_target(process):
        return
    if not await asyncio.to_thread(kill_tree_sync, process.pid, platform="win32"):
        with contextlib.suppress(ProcessLookupError):
            process.kill()
