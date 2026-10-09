"""Checking whether a test's child process is still alive, on both platforms.

Never probe with `os.kill(pid, 0)` on Windows: there it terminates the process (any signal
other than CTRL_C/CTRL_BREAK becomes TerminateProcess), so a "still alive?" check would make
a kill test pass by itself.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True,
            check=False,
        ).stdout.decode("utf-8", errors="replace")
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed process whose parent has not reaped it yet still answers kill(0) as a zombie.
    status = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, check=False)
    return status.stdout.strip()[:1] not in (b"Z", b"")


async def wait_gone(pid: int, timeout: float = 10.0) -> bool:
    """`True` once `pid` is gone, `False` if it is still alive after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        await asyncio.sleep(0.1)
    return False
