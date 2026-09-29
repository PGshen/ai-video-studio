"""搜索提供方协议与数据结构（设计 §2.2 `search/`；计划 M4 T1）。

纯能力层：只依赖 `config`，不访问数据库，不知道项目和阶段。供应商相关的
细节（端点、字段、错误码）都留在具体实现里，调用方只看这里的类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class SearchError(Exception):
    """搜索/抓取失败。`message` 是给模型看的中文说明，不包含 API key。"""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    published: str | None = None
    score: float | None = None


@dataclass(frozen=True, slots=True)
class SearchResponse:
    query: str
    hits: list[SearchHit] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    url: str
    text: str
    """已按 `max_chars` 截断后的正文。"""
    truncated: bool
    total_chars: int
    """截断前的正文长度。"""


class SearchProvider(Protocol):
    async def search(
        self, query: str, *, max_results: int = 5, recency_days: int | None = None
    ) -> SearchResponse: ...

    async def extract(self, url: str, *, max_chars: int) -> ExtractedPage: ...
