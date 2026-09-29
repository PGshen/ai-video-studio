"""Tavily 搜索提供方（计划 M4 T1）。

端点、字段和错误码见 `docs/references/tavily.md`（2026-09-29 查官方文档）。
重试策略沿用 `engines/tts/volcengine.py`：只重试 429/5xx/超时类错误，指数退避。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from studio.search.base import ExtractedPage, SearchError, SearchHit, SearchResponse

_DEFAULT_BASE_URL = "https://api.tavily.com"
_MAX_RESULTS_LIMIT = 20
_RETRYABLE_STATUS = {429}
_QUOTA_STATUS = {432, 433}

logger = logging.getLogger(__name__)


def _time_range(days: int) -> str:
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 31:
        return "month"
    return "year"


class TavilyProvider:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        max_retries: int = 2,
        retry_base_delay_seconds: float = 1.0,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max(0, max_retries)
        self._retry_base_delay_seconds = max(0.0, retry_base_delay_seconds)
        self._timeout_seconds = timeout_seconds

    async def search(
        self, query: str, *, max_results: int = 5, recency_days: int | None = None
    ) -> SearchResponse:
        cleaned = query.strip()
        if not cleaned:
            raise SearchError("搜索词不能为空。")
        body: dict[str, Any] = {
            "query": cleaned,
            "search_depth": "basic",
            "max_results": max(1, min(max_results, _MAX_RESULTS_LIMIT)),
            "include_published_date": True,
        }
        if recency_days is not None:
            body["time_range"] = _time_range(recency_days)
        data = await self._post("/search", body)
        results = data.get("results")
        if not isinstance(results, list):
            raise SearchError("搜索服务返回了无法识别的结果。")
        hits: list[SearchHit] = []
        for item in results:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                continue
            score = item.get("score")
            published = item.get("published_date")
            hits.append(
                SearchHit(
                    title=str(item.get("title") or item["url"]),
                    url=item["url"],
                    snippet=str(item.get("content") or ""),
                    published=published if isinstance(published, str) and published else None,
                    score=float(score) if isinstance(score, int | float) else None,
                )
            )
        return SearchResponse(query=cleaned, hits=hits)

    async def extract(self, url: str, *, max_chars: int) -> ExtractedPage:
        data = await self._post("/extract", {"urls": [url], "format": "markdown"})
        results = data.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict) and isinstance(item.get("raw_content"), str):
                    text = item["raw_content"].strip()
                    if not text:
                        break
                    truncated = len(text) > max_chars
                    return ExtractedPage(
                        url=url,
                        text=text[:max_chars],
                        truncated=truncated,
                        total_chars=len(text),
                    )
        failed = data.get("failed_results")
        reason = ""
        if isinstance(failed, list) and failed and isinstance(failed[0], dict):
            reason = str(failed[0].get("error") or "")
        detail = f"：{reason}" if reason else "（没有提取到正文）"
        raise SearchError(f"无法抓取 {url}{detail}")

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        total_attempts = self._max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(
                        f"{self._base_url}{path}", json=body, headers=headers
                    )
                return self._parse(response)
            except SearchError as exc:
                if not exc.retryable or attempt == total_attempts:
                    raise
            except httpx.TimeoutException as exc:
                if attempt == total_attempts:
                    raise SearchError("搜索服务请求超时。", retryable=True) from exc
            except httpx.RequestError as exc:
                if attempt == total_attempts:
                    raise SearchError(
                        f"搜索服务网络错误（{type(exc).__name__}）。", retryable=True
                    ) from exc
            delay = self._retry_base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Tavily %s 请求失败，%.1f 秒后重试（%d/%d）", path, delay, attempt, total_attempts
            )
            await asyncio.sleep(delay)
        raise RuntimeError("unreachable")

    @staticmethod
    def _parse(response: httpx.Response) -> dict[str, Any]:
        status = response.status_code
        if status == 401:
            raise SearchError("TAVILY_API_KEY 缺失或无效，请检查 backend/.env。")
        if status in _QUOTA_STATUS:
            raise SearchError("Tavily 额度已用尽或超出套餐限制。")
        if status in (400, 422):
            raise SearchError(f"搜索请求参数不合法（HTTP {status}）。")
        if status in _RETRYABLE_STATUS or status >= 500:
            raise SearchError(f"搜索服务暂时不可用（HTTP {status}）。", retryable=True)
        if not 200 <= status < 300:
            raise SearchError(f"搜索服务返回了意外的状态（HTTP {status}）。")
        try:
            data = response.json()
        except ValueError as exc:
            raise SearchError("搜索服务返回的不是合法 JSON。") from exc
        if not isinstance(data, dict):
            raise SearchError("搜索服务返回了无法识别的结果。")
        return data
