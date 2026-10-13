"""codex 启动的命令进程（codex-runtime T4）。

codex 把模型执行的命令放在**独立的进程组**里（codex.md「续会话、取消与用量」）：SIGINT 时它
自己收掉这些进程，强杀 codex 则留下父进程变成 1 的孤儿，而且孤儿还握着我们读 stdout 的管道。
所以强杀前先记下 codex 全部后代所在的进程组，杀完 codex 再逐个杀这些组。

只用标准库（`ps`），不引入 psutil。Windows 上没有进程组的概念可用，`proc.kill_tree` 的
`taskkill /T` 本身就按进程树杀，这里返回空。
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Iterable, Sequence

from studio import proc

ProcessRow = tuple[int, int, int]
"""`(pid, ppid, pgid)`。"""


def descendants(root: int, table: Sequence[ProcessRow]) -> list[tuple[int, int]]:
    """`root` 的全部后代 `(pid, pgid)`（不含 `root` 自己）。"""
    children: dict[int, list[ProcessRow]] = {}
    for row in table:
        children.setdefault(row[1], []).append(row)
    out: list[tuple[int, int]] = []
    stack = [root]
    while stack:
        for pid, _ppid, pgid in children.get(stack.pop(), []):
            out.append((pid, pgid))
            stack.append(pid)
    return out


def process_table() -> list[ProcessRow]:
    if sys.platform == "win32":
        return []
    try:
        result = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid=,pgid="],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **proc.spawn_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows: list[ProcessRow] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            rows.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return rows


def descendant_groups(root: int) -> set[int]:
    """`root` 后代所在的进程组（不含 `root` 自己的组：那一组由 `proc.kill_tree` 负责）。"""
    own = {pgid for pid, _ppid, pgid in process_table() if pid == root}
    return {pgid for _pid, pgid in descendants(root, process_table())} - own - {0, 1}


def kill_groups(pgids: Iterable[int]) -> None:
    if sys.platform == "win32":
        return
    for pgid in pgids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)
