"""Renames and deletes that wait briefly for another reader (windows-native design §12, P12).

On Windows a file another handle has open cannot be replaced (WinError 5) or deleted
(WinError 32) — e.g. the API is still streaming the old `final.mp4` or `music.wav` to the
player when a re-render finishes, or an editor has a workspace file open during `guard`.
These wrappers retry only `PermissionError`, only on Windows, for about a second; on POSIX
such an error is a real permission problem and is raised at once.

This module imports nothing from `studio` (import-linter contract), like `studio.proc`.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

_BUDGET_SECONDS = 1.0
_FIRST_DELAY = 0.02


def retrying[T](
    operation: Callable[[], T],
    *,
    platform: str | None = None,
    sleep: Callable[[float], object] = time.sleep,
) -> T:
    """Run `operation`; on Windows retry a `PermissionError` with growing pauses for about a
    second, then raise the last one. Blocking: callers on the event loop accept up to ~1 s
    only on this error path."""
    if (platform or sys.platform) != "win32":
        return operation()
    waited, delay = 0.0, _FIRST_DELAY
    while True:
        try:
            return operation()
        except PermissionError:
            if waited >= _BUDGET_SECONDS:
                raise
            pause = min(delay, _BUDGET_SECONDS - waited + 0.001)
            sleep(pause)
            waited += pause
            delay = min(delay * 2, 0.2)


def replace(src: Path | str, dst: Path | str) -> None:
    retrying(lambda: os.replace(src, dst))


def unlink(path: Path, *, missing_ok: bool = False) -> None:
    retrying(lambda: path.unlink(missing_ok=missing_ok))


def rmtree(path: Path | str, *, ignore_errors: bool = False) -> None:
    """`shutil.rmtree` that waits for readers; with `ignore_errors` a tree that is still in use
    after the wait is left behind silently, as before."""

    def remove() -> None:
        if os.path.lexists(path):
            shutil.rmtree(path)

    try:
        retrying(remove)
    except OSError:
        if not ignore_errors:
            raise
