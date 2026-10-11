"""Browser launch options and the renderer signature (ADR 0028: frames default to the GPU)."""

from __future__ import annotations

import pytest

from studio.config import get_settings
from studio.engines.render.html.browser import HtmlBrowser, launch_options


def test_gpu_uses_the_full_chromium_new_headless() -> None:
    assert launch_options(gpu=True) == {"channel": "chromium"}


def test_software_keeps_the_headless_shell() -> None:
    assert launch_options(gpu=False) == {}


def test_the_default_follows_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_RENDER_GPU", "false")
    get_settings.cache_clear()
    assert HtmlBrowser().gpu is False
    monkeypatch.setenv("STUDIO_RENDER_GPU", "true")
    get_settings.cache_clear()
    assert HtmlBrowser().gpu is True
    assert HtmlBrowser(gpu=False).gpu is False
    get_settings.cache_clear()


@pytest.mark.slow
@pytest.mark.macos_only("every Mac has a Metal GPU; other hosts may legitimately lack one")
@pytest.mark.parametrize(("gpu", "needle"), [(True, "Metal"), (False, "SwiftShader")])
async def test_renderer_signature_names_the_actual_renderer(gpu: bool, needle: str) -> None:
    async with HtmlBrowser(gpu=gpu) as browser:
        signature = await browser.renderer_signature()
        assert await browser.renderer_signature() == signature  # cached
    assert needle in signature
    assert signature.startswith("Chromium ")
