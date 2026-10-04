"""`engines.render.html.pool.BrowserPool`：并发上限、排队、崩溃重建、空闲关闭（假浏览器）。"""

from __future__ import annotations

import asyncio

import pytest

from studio.engines.render.html.assemble import AssembledPage
from studio.engines.render.html.browser import PageNotReady
from studio.engines.render.html.pool import (
    BrowserPool,
    PoolBusy,
    close_browser_pool,
    get_browser_pool,
    set_browser_pool,
)

PAGE = AssembledPage(html="<p/>", routes={}, scripts={})


class FakePage:
    def __init__(self, browser: FakeBrowser) -> None:
        self.errors: list[str] = []
        self.poisoned = False
        self.closed = False
        self._browser = browser

    async def render_jpeg(self, t: float) -> bytes:
        return b""

    async def render_hash(self, t: float) -> str:
        return ""

    async def set_timeline(self, timeline: object) -> None:
        return None

    async def close(self) -> None:
        self.closed = True
        self._browser.live -= 1


class FakeBrowser:
    def __init__(self, log: list[FakeBrowser], *, open_delay: float = 0.0) -> None:
        self.connected = True
        self.closed = False
        self.live = 0
        self.peak = 0
        self.opened: list[FakePage] = []
        self.fail_open_with: Exception | None = None
        self._open_delay = open_delay
        log.append(self)

    async def open_page(self, page: AssembledPage) -> FakePage:
        if self.fail_open_with is not None:
            raise self.fail_open_with
        self.live += 1
        self.peak = max(self.peak, self.live)
        await asyncio.sleep(self._open_delay)
        fake = FakePage(self)
        self.opened.append(fake)
        return fake

    async def close(self) -> None:
        self.closed = True
        self.connected = False


def _pool(
    log: list[FakeBrowser],
    *,
    max_pages: int = 2,
    idle_seconds: float = 600.0,
    queue_timeout: float = 60.0,
) -> BrowserPool:
    async def launcher() -> FakeBrowser:
        return FakeBrowser(log, open_delay=0.05)

    return BrowserPool(
        max_pages=max_pages,
        idle_seconds=idle_seconds,
        queue_timeout=queue_timeout,
        launcher=launcher,
    )


async def test_concurrency_is_capped_and_waiters_get_their_turn() -> None:
    log: list[FakeBrowser] = []
    pool = _pool(log, max_pages=2)

    async def use() -> None:
        async with pool.acquire(PAGE):
            await asyncio.sleep(0.05)

    await asyncio.gather(*(use() for _ in range(5)))
    assert len(log) == 1
    assert log[0].peak == 2
    assert len(log[0].opened) == 5 and all(p.closed for p in log[0].opened)
    await pool.close()


async def test_queue_timeout_raises_pool_busy() -> None:
    log: list[FakeBrowser] = []
    pool = _pool(log, max_pages=1, queue_timeout=0.05)
    async with pool.acquire(PAGE):
        with pytest.raises(PoolBusy):
            async with pool.acquire(PAGE):
                pass
    async with pool.acquire(PAGE):  # 槽位已归还
        pass
    await pool.close()


async def test_disconnected_browser_is_rebuilt_for_the_next_call() -> None:
    log: list[FakeBrowser] = []
    pool = _pool(log)
    async with pool.acquire(PAGE):
        pass
    log[0].connected = False  # 模拟 Chromium 被杀
    async with pool.acquire(PAGE) as page:
        assert page is log[1].opened[0]
    assert log[0].closed and len(log) == 2
    await pool.close()


async def test_open_failure_from_a_crashed_browser_is_retried_once() -> None:
    log: list[FakeBrowser] = []
    pool = _pool(log)
    async with pool.acquire(PAGE):
        pass
    log[0].fail_open_with = RuntimeError("Target closed")
    log[0].connected = False
    async with pool.acquire(PAGE):
        pass
    assert len(log) == 2
    await pool.close()


async def test_open_failure_with_live_browser_is_not_retried() -> None:
    log: list[FakeBrowser] = []
    pool = _pool(log)
    async with pool.acquire(PAGE):
        pass
    log[0].fail_open_with = ValueError("bad page")
    with pytest.raises(ValueError):
        async with pool.acquire(PAGE):
            pass
    assert len(log) == 1
    await pool.close()


async def test_user_errors_propagate_without_rebuilding() -> None:
    log: list[FakeBrowser] = []
    pool = _pool(log)
    async with pool.acquire(PAGE):
        pass
    log[0].fail_open_with = PageNotReady("语法错误", ["pageerror: x"])
    with pytest.raises(PageNotReady):
        async with pool.acquire(PAGE):
            pass
    assert len(log) == 1
    await pool.close()


async def test_poisoned_page_makes_the_next_call_use_a_fresh_browser() -> None:
    log: list[FakeBrowser] = []
    pool = _pool(log)
    async with pool.acquire(PAGE) as page:
        page.poisoned = True
    assert log[0].closed
    async with pool.acquire(PAGE):
        pass
    assert len(log) == 2
    await pool.close()


async def test_idle_browser_is_closed_and_relaunched_on_demand() -> None:
    log: list[FakeBrowser] = []
    pool = _pool(log, idle_seconds=0.05)
    async with pool.acquire(PAGE):
        pass
    await asyncio.sleep(0.2)
    assert log[0].closed
    async with pool.acquire(PAGE):
        pass
    assert len(log) == 2
    await pool.close()


async def test_close_is_idempotent() -> None:
    log: list[FakeBrowser] = []
    pool = _pool(log)
    async with pool.acquire(PAGE):
        pass
    await pool.close()
    await pool.close()
    assert log[0].closed


async def test_module_level_pool_can_be_injected_and_closed() -> None:
    log: list[FakeBrowser] = []
    injected = _pool(log)
    set_browser_pool(injected)
    assert get_browser_pool() is injected
    async with injected.acquire(PAGE):
        pass
    await close_browser_pool()
    assert log[0].closed
    set_browser_pool(None)
