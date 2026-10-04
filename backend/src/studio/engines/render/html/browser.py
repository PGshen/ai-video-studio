"""无头 Chromium 的页面封装（设计 §5.1、§5.4）。

`HtmlBrowser` 启动浏览器并打开装配好的页面；`HtmlPage` 提供按时间取帧、替换时间轴等操作。
文件通过 `page.route` 在 `http://studio.local/` 下直接供给，不开端口。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import unquote

from playwright.async_api import Browser, BrowserContext, Page, Route, async_playwright
from playwright.async_api import Error as PlaywrightError

from studio.engines.render.html.assemble import AssembledPage

INSTALL_HINT = "uv run playwright install chromium"
ORIGIN = "http://studio.local/"
READY_TIMEOUT_SECONDS = 15.0
RENDER_TIMEOUT_SECONDS = 10.0
_MAX_ERROR_CHARS = 1500


class ChromiumUnavailable(RuntimeError):
    def __init__(self, detail: str = ""):
        super().__init__(
            f"无法启动 Chromium，请先运行：{INSTALL_HINT}" + (f"\n{detail}" if detail else "")
        )


class PageNotReady(RuntimeError):
    def __init__(self, message: str, errors: list[str]):
        self.errors = list(errors)
        details = "\n".join(self.errors)
        super().__init__(message + (f"\n{details}" if details else ""))


class RenderTimeout(RuntimeError):
    def __init__(self, t: float, seconds: float):
        self.t = t
        super().__init__(f"t={t:.3f}s 的帧在 {seconds:.0f} 秒内没有渲染完成（可能有死循环）")


class SceneRenderError(RuntimeError):
    """页面里 `renderAt` 抛出的异常（消息已带 `[scene <id> @lt=…]` 前缀和 JS 堆栈）。"""


class BrowserClosed(SceneRenderError):
    """浏览器或页面在调用进行中被关闭（崩溃、被杀）：调用方可以换新页面重试一次。"""


class PageLike(Protocol):
    errors: list[str]
    poisoned: bool

    async def render_jpeg(self, t: float) -> bytes: ...

    async def render_hash(self, t: float) -> str: ...

    async def set_timeline(self, timeline: Mapping[str, Any]) -> None: ...

    async def close(self) -> None: ...


class BrowserLike(Protocol):
    @property
    def connected(self) -> bool: ...

    async def open_page(self, page: AssembledPage) -> PageLike: ...

    async def close(self) -> None: ...


def _clean(exc: PlaywrightError) -> str:
    text = str(exc)
    for prefix in ("Page.evaluate: ", "Error: "):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text[:_MAX_ERROR_CHARS]


class HtmlPage:
    def __init__(
        self,
        context: BrowserContext,
        page: Page,
        errors: list[str],
        *,
        render_timeout: float = RENDER_TIMEOUT_SECONDS,
    ) -> None:
        self._context = context
        self._page = page
        self.errors = errors
        self.poisoned = False
        self.close_failed = False
        """关闭 context 失败（渲染进程可能还卡着）：池据此换掉整个浏览器。"""
        self._render_timeout = render_timeout

    async def _call(self, expression: str, arg: Any, t: float) -> Any:
        try:
            return await asyncio.wait_for(
                self._page.evaluate(expression, arg), self._render_timeout
            )
        except TimeoutError as exc:
            self.poisoned = True
            raise RenderTimeout(t, self._render_timeout) from exc
        except PlaywrightError as exc:
            if "closed" in str(exc).lower():
                self.poisoned = True
                raise BrowserClosed(_clean(exc)) from exc
            raise SceneRenderError(_clean(exc)) from exc

    async def render_jpeg(self, t: float) -> bytes:
        data = await self._call(
            "t => { window.renderAt(t); "
            "return document.getElementById('c').toDataURL('image/jpeg', 0.92); }",
            t,
            t,
        )
        return base64.b64decode(data.split(",", 1)[1])

    async def render_hash(self, t: float) -> str:
        data = await self._call(
            "t => { window.renderAt(t); "
            "return document.getElementById('c').toDataURL('image/png'); }",
            t,
            t,
        )
        return hashlib.sha1(data.encode()).hexdigest()

    async def set_timeline(self, timeline: Mapping[str, Any]) -> None:
        await self._call("tl => { window.__TIMELINE__ = tl; }", dict(timeline), 0.0)

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        """测试与调试用：在页面里执行一段表达式。"""
        return await self._call(expression, arg, 0.0)

    async def close(self) -> None:
        try:
            await asyncio.wait_for(self._context.close(), 5.0)
        except (TimeoutError, PlaywrightError):
            self.poisoned = True
            self.close_failed = True


class HtmlBrowser:
    def __init__(
        self,
        *,
        ready_timeout: float = READY_TIMEOUT_SECONDS,
        render_timeout: float = RENDER_TIMEOUT_SECONDS,
    ) -> None:
        self._ready_timeout = ready_timeout
        self._render_timeout = render_timeout
        self._playwright: Any = None
        self._browser: Browser | None = None

    @property
    def connected(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def start(self) -> HtmlBrowser:
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch()
        except PlaywrightError as exc:
            await self._playwright.stop()
            self._playwright = None
            raise ChromiumUnavailable(str(exc).splitlines()[0] if str(exc) else "") from exc
        except BaseException:
            await self._playwright.stop()
            self._playwright = None
            raise
        return self

    async def __aenter__(self) -> HtmlBrowser:
        return await self.start()

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = self._playwright = None
        try:
            if browser is not None:
                await asyncio.wait_for(browser.close(), 5.0)
        except (TimeoutError, PlaywrightError):
            pass
        finally:
            if playwright is not None:
                try:
                    await asyncio.wait_for(playwright.stop(), 5.0)
                except (TimeoutError, PlaywrightError):
                    pass

    async def open_page(self, page: AssembledPage) -> HtmlPage:
        if self._browser is None:
            raise ChromiumUnavailable("浏览器尚未启动")
        context = await self._browser.new_context(viewport={"width": 1920, "height": 1080})
        errors: list[str] = []
        try:
            html_page = await context.new_page()
        except BaseException:
            await context.close()
            raise
        result = HtmlPage(context, html_page, errors, render_timeout=self._render_timeout)

        async def handle(route: Route) -> None:
            path = unquote(route.request.url.removeprefix(ORIGIN).split("?", 1)[0])
            if path in ("", "index.html"):
                await route.fulfill(body=page.html, content_type="text/html; charset=utf-8")
                return
            if path.startswith("scripts/") and path[len("scripts/") :] in page.scripts:
                await route.fulfill(
                    body=page.scripts[path[len("scripts/") :]],
                    content_type="text/javascript; charset=utf-8",
                )
                return
            file = page.routes.get(path)
            if file is None or not file.is_file():
                await route.fulfill(status=404, body="not found")
                return
            await route.fulfill(
                body=file.read_bytes(), content_type=_content_type(file.suffix.lower())
            )

        try:
            await context.route(ORIGIN + "**", handle)
        except BaseException:
            await result.close()
            raise
        html_page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        html_page.on(
            "console",
            lambda m: (
                errors.append(f"console.{m.type}: {m.text}")
                if m.type in ("error", "warning")
                else None
            ),
        )
        try:
            await asyncio.wait_for(self._load(html_page), self._ready_timeout)
        except TimeoutError as exc:
            await result.close()
            raise PageNotReady(f"页面在 {self._ready_timeout:.0f} 秒内没有就绪", errors) from exc
        except PlaywrightError as exc:
            await result.close()
            raise PageNotReady(_clean(exc), errors) from exc
        return result

    @staticmethod
    async def _load(page: Page) -> None:
        await page.goto(ORIGIN + "index.html")
        await page.evaluate("window.ready")


_CONTENT_TYPES: dict[str, str] = {
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _content_type(suffix: str) -> str:
    return _CONTENT_TYPES.get(suffix, "application/octet-stream")
