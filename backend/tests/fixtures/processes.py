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


def process_table() -> list[tuple[int, int, str]]:
    """`(pid, ppid, command line)` of every process (`ps` on POSIX, CIM on Windows)."""
    if sys.platform == "win32":
        script = (
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            "Get-CimInstance Win32_Process | ForEach-Object "
            '{ "$($_.ProcessId) $($_.ParentProcessId) $($_.CommandLine)" }'
        )
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    else:
        argv = ["ps", "-axo", "pid=,ppid=,command="]
    out = subprocess.run(argv, capture_output=True, check=True).stdout
    rows = []
    for line in out.decode("utf-8", errors="replace").splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2] if len(parts) == 3 else ""))
    return rows


def descendants(root: int) -> list[tuple[int, str]]:
    """`(pid, command line)` of every process below `root`."""
    rows = process_table()
    mine = {root}
    grew = True
    while grew:
        grew = False
        for pid, ppid, _ in rows:
            if ppid in mine and pid not in mine:
                mine.add(pid)
                grew = True
    return [(pid, command) for pid, _, command in rows if pid in mine and pid != root]


async def wait_gone(pid: int, timeout: float = 10.0) -> bool:
    """`True` once `pid` is gone, `False` if it is still alive after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        await asyncio.sleep(0.1)
    return False
