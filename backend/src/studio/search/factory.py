"""搜索提供方工厂（计划 M4 T1）。

真实 key 按固定环境变量名读取（不进 `Settings`），原则同 `model_profiles.api_key_env`
和 `engines/tts/factory.py`——真实 key 不落进配置字段。
"""

from __future__ import annotations

import os

from studio.search.tavily import TavilyProvider

TAVILY_API_KEY_ENV = "TAVILY_API_KEY"


def build_search_provider() -> TavilyProvider:
    api_key = os.environ.get(TAVILY_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"环境变量 {TAVILY_API_KEY_ENV} 未设置，请在 backend/.env 中配置。")
    return TavilyProvider(api_key=api_key)
