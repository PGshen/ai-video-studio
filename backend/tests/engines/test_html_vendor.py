"""Bundled third-party libraries for the HTML engine (ADR 0028)."""

from __future__ import annotations

import re

import pytest

from studio.engines.render.html.assemble import AssembledPage
from studio.engines.render.html.browser import HtmlBrowser, HtmlPage
from studio.engines.render.html.vendor import (
    THREE_LICENSE,
    THREE_SCRIPT_NAME,
    three_script,
    three_version,
)


def test_three_version_is_pinned() -> None:
    assert re.fullmatch(r"0\.\d+\.\d+", three_version())


def test_three_license_is_bundled() -> None:
    assert "MIT" in THREE_LICENSE.read_text(encoding="utf-8")


def test_three_script_is_a_classic_script_defining_a_global() -> None:
    source = three_script()
    assert source.startswith("var THREE=(function(")
    assert "require(" not in source
    assert not re.search(r"^\s*(import|export)\b", source, re.MULTILINE)


@pytest.mark.slow
async def test_three_loads_in_chromium() -> None:
    page = AssembledPage(
        html=(
            '<!doctype html><canvas id="c" width="16" height="16"></canvas>'
            f'<script src="scripts/{THREE_SCRIPT_NAME}"></script>'
            "<script>window.ready = Promise.resolve();</script>"
        ),
        routes={},
        scripts={THREE_SCRIPT_NAME: three_script()},
    )
    async with HtmlBrowser(ready_timeout=15, render_timeout=5) as browser:
        opened = await browser.open_page(page)
        assert isinstance(opened, HtmlPage)
        revision = await opened.evaluate("window.THREE.REVISION")
        await opened.close()
    assert revision == three_version().split(".")[1]
