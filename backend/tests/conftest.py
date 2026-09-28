from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """每个测试前后清空 get_settings() 的缓存，避免用例间互相污染。"""
    from studio.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
