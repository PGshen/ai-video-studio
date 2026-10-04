"""api 进程内常驻的浏览器池（设计 §5.4）。

懒启动；并发页面数有上限，排队超时抛 `PoolBusy`；浏览器断开或页面作废后自动重建并重试一次；
空闲一段时间后关闭浏览器。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from studio.engines.render.html.assemble import AssembledPage
from studio.engines.render.html.browser import (
    BrowserLike,
    HtmlBrowser,
    PageLike,
    PageNotReady,
    RenderTimeout,
)

MAX_PAGES = 2
IDLE_SECONDS = 600.0
QUEUE_TIMEOUT_SECONDS = 60.0


class PoolBusy(RuntimeError):
    def __init__(self, seconds: float):
        super().__init__(f"预览繁忙：排队超过 {seconds:.0f} 秒，请稍后再试")


async def _launch_default() -> BrowserLike:
    return await HtmlBrowser().start()


class BrowserPool:
    def __init__(
        self,
        *,
        max_pages: int = MAX_PAGES,
        idle_seconds: float = IDLE_SECONDS,
        queue_timeout: float = QUEUE_TIMEOUT_SECONDS,
        launcher: Callable[[], Awaitable[BrowserLike]] = _launch_default,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_pages)
        self._idle_seconds = idle_seconds
        self._queue_timeout = queue_timeout
        self._launcher = launcher
        self._browser: BrowserLike | None = None
        self._lock = asyncio.Lock()
        self._active = 0
        self._idle_task: asyncio.Task[None] | None = None

    async def _ensure_browser(self) -> BrowserLike:
        async with self._lock:
            if self._browser is None or not self._browser.connected:
                if self._browser is not None:
                    await self._discard_browser()
                self._browser = await self._launcher()
            return self._browser

    async def _discard_browser(self) -> None:
        browser, self._browser = self._browser, None
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()

    def _cancel_idle(self) -> None:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    def _schedule_idle(self) -> None:
        self._cancel_idle()
        self._idle_task = asyncio.ensure_future(self._close_when_idle())

    async def _close_when_idle(self) -> None:
        await asyncio.sleep(self._idle_seconds)
        if self._active == 0:
            async with self._lock:
                await self._discard_browser()

    async def _open(self, page: AssembledPage) -> PageLike:
        browser = await self._ensure_browser()
        try:
            return await browser.open_page(page)
        except (PageNotReady, RenderTimeout):
            raise
        except Exception:
            if browser.connected:
                raise
            browser = await self._ensure_browser()  # 崩溃：重建并重试一次
            return await browser.open_page(page)

    @asynccontextmanager
    async def acquire(self, page: AssembledPage) -> AsyncIterator[PageLike]:
        try:
            await asyncio.wait_for(self._semaphore.acquire(), self._queue_timeout)
        except TimeoutError as exc:
            raise PoolBusy(self._queue_timeout) from exc
        self._active += 1
        self._cancel_idle()
        opened: PageLike | None = None
        try:
            opened = await self._open(page)
            yield opened
        finally:
            if opened is not None:
                await opened.close()
                if opened.poisoned:
                    async with self._lock:
                        await self._discard_browser()  # 页面卡死：整个浏览器换新
            self._active -= 1
            self._semaphore.release()
            if self._active == 0:
                self._schedule_idle()

    async def close(self) -> None:
        self._cancel_idle()
        async with self._lock:
            await self._discard_browser()


_pool: BrowserPool | None = None


def get_browser_pool() -> BrowserPool:
    global _pool
    if _pool is None:
        _pool = BrowserPool()
    return _pool


def set_browser_pool(pool: BrowserPool | None) -> None:
    """测试注入替身；传 `None` 恢复懒创建。"""
    global _pool
    _pool = pool


async def close_browser_pool() -> None:
    global _pool
    pool, _pool = _pool, None
    if pool is not None:
        await pool.close()
