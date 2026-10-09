"""真实 Chromium 下浏览器池的崩溃恢复与空闲回收（`-m slow`；2B T8，TD-69 ⑤）。

只杀本测试进程自己的后代里的 Chromium 主进程，不碰机器上别的浏览器。
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.html_engine import projects as fx
from studio.engines.render.html.assemble import assemble
from studio.engines.render.html.browser import BrowserClosed
from studio.engines.render.html.pool import BrowserPool

pytestmark = pytest.mark.slow


def _descendants() -> list[tuple[int, str]]:
    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    rows = []
    for line in out:
        parts = line.split(None, 2)
        if len(parts) == 3:
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    mine = {os.getpid()}
    grew = True
    while grew:
        grew = False
        for pid, ppid, _ in rows:
            if ppid in mine and pid not in mine:
                mine.add(pid)
                grew = True
    return [(pid, command) for pid, _, command in rows if pid in mine and pid != os.getpid()]


def _browser_main_pids() -> list[int]:
    """Chromium 主进程：Playwright 启动（带 `--remote-debugging-pipe`），不是 `--type=` 子进程。"""
    return [
        pid
        for pid, command in _descendants()
        if "--remote-debugging-pipe" in command and "--type=" not in command
    ]


@pytest.fixture
def page(tmp_path: Path):
    fx.write_project(
        tmp_path, scenes={"s-hook": fx.PURE_SCENE_PLAIN, "s-explain": fx.PURE_SCENE_PLAIN}
    )
    return assemble(tmp_path, fx.TIMELINE)


def _hard_kill(pid: int) -> None:
    if sys.platform == "win32":
        os.kill(pid, signal.SIGTERM)  # TerminateProcess: as abrupt as SIGKILL
    else:
        os.kill(pid, signal.SIGKILL)


async def test_pool_recovers_after_the_browser_process_is_sigkilled(page) -> None:
    pool = BrowserPool()
    try:
        async with pool.acquire(page) as first:
            assert len(await first.render_jpeg(0.5)) > 1000
        (pid,) = _browser_main_pids()
        _hard_kill(pid)
        await asyncio.sleep(0.5)
        async with pool.acquire(page) as second:  # next call rebuilds the browser
            assert len(await second.render_jpeg(0.5)) > 1000
        assert _browser_main_pids() and pid not in _browser_main_pids()
    finally:
        await pool.close()


async def test_killing_the_browser_mid_session_surfaces_browser_closed(page) -> None:
    pool = BrowserPool()
    try:
        async with pool.acquire(page) as live:
            await live.render_jpeg(0.5)
            for pid in _browser_main_pids():
                _hard_kill(pid)
            await asyncio.sleep(0.5)
            with pytest.raises(BrowserClosed):
                await live.render_jpeg(0.6)
        async with pool.acquire(page) as fresh:
            assert len(await fresh.render_jpeg(0.5)) > 1000
    finally:
        await pool.close()


async def test_idle_pool_closes_the_browser_and_leaves_no_processes(page) -> None:
    pool = BrowserPool(idle_seconds=0.5)
    try:
        async with pool.acquire(page) as live:
            await live.render_jpeg(0.5)
        assert _browser_main_pids()
        await asyncio.sleep(2.0)
        assert _browser_main_pids() == []
    finally:
        await pool.close()
