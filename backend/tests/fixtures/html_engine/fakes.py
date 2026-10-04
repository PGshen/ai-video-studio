"""HTML 引擎测试用的假浏览器：按脚本返回帧与哈希，不需要 Chromium。"""

from __future__ import annotations

import copy
import hashlib
import io
from collections.abc import Callable, Mapping
from typing import Any

from PIL import Image

from fixtures.html_engine import projects as fx
from studio.engines.render.html.assemble import AssembledPage


def jpeg(*, flat: bool = False) -> bytes:
    image = Image.new("RGB", (64, 36), (20, 20, 20))
    if not flat:
        for x in range(64):
            for y in range(36):
                image.putpixel((x, y), ((x * 4) % 256, (y * 7) % 256, 128))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def digest(*parts: object) -> str:
    return hashlib.sha1(repr(parts).encode()).hexdigest()


def beat_starts(timeline: Mapping[str, Any]) -> list[float]:
    return [b["start"] for n in timeline["narration"] for b in n["beats"]]


class ScriptedPage:
    def __init__(self, behaviour: Behaviour) -> None:
        self.errors: list[str] = list(behaviour.page_errors)
        self.poisoned = False
        self.timeline: Mapping[str, Any] = copy.deepcopy(fx.TIMELINE)
        self._b = behaviour

    async def render_jpeg(self, t: float) -> bytes:
        return self._b.jpeg_fn(t)

    async def render_hash(self, t: float) -> str:
        return self._b.hash_fn(t, self.timeline)

    async def set_timeline(self, timeline: Mapping[str, Any]) -> None:
        self.timeline = timeline

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        return self._b.pads

    async def close(self) -> None:
        return None


class Behaviour:
    def __init__(self) -> None:
        self.jpeg_fn: Callable[[float], bytes] = lambda t: jpeg()
        self.hash_fn: Callable[[float, Mapping[str, Any]], str] = lambda t, tl: digest(
            t, beat_starts(tl)
        )
        self.page_errors: list[str] = []
        self.open_error: Exception | None = None
        self.pads: dict[str, float] = {}
        self.opened = 0


class ScriptedBrowser:
    def __init__(self, behaviour: Behaviour) -> None:
        self.connected = True
        self._b = behaviour

    async def open_page(self, page: AssembledPage) -> ScriptedPage:
        if self._b.open_error is not None:
            raise self._b.open_error
        self._b.opened += 1
        return ScriptedPage(self._b)

    async def close(self) -> None:
        self.connected = False
