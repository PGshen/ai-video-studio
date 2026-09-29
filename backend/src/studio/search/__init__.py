"""搜索提供方接口与 Tavily 实现（设计 §2.2；计划 M4 T1）。"""

from __future__ import annotations

from studio.search.base import (
    ExtractedPage,
    SearchError,
    SearchHit,
    SearchProvider,
    SearchResponse,
)
from studio.search.factory import build_search_provider
from studio.search.tavily import TavilyProvider

__all__ = [
    "ExtractedPage",
    "SearchError",
    "SearchHit",
    "SearchProvider",
    "SearchResponse",
    "TavilyProvider",
    "build_search_provider",
]
