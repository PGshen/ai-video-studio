"""`search` 模块测试（计划 M4 T1）：Tavily 提供方，全程挡住真实网络。"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from studio.search import SearchError, SearchResponse, build_search_provider
from studio.search.tavily import TavilyProvider

_BASE = "https://tavily.test"
_KEY = "tvly-secret-key"


def _provider(max_retries: int = 2) -> TavilyProvider:
    return TavilyProvider(
        api_key=_KEY, base_url=_BASE, max_retries=max_retries, retry_base_delay_seconds=0.0
    )


def _search_payload(*items: dict) -> dict:
    return {"query": "q", "results": list(items), "response_time": 0.5}


def _item(n: int, **extra: object) -> dict:
    return {
        "title": f"标题{n}",
        "url": f"https://example.com/{n}",
        "content": f"摘要{n}",
        "score": 0.9 - n / 100,
        **extra,
    }


@pytest.mark.asyncio
@respx.mock
async def test_search_normalizes_results_and_sends_expected_request() -> None:
    route = respx.post(f"{_BASE}/search").mock(
        return_value=httpx.Response(
            200, json=_search_payload(_item(1, published_date="2026-09-01"), _item(2))
        )
    )

    response = await _provider().search("排序算法", max_results=3)

    assert isinstance(response, SearchResponse)
    assert response.query == "排序算法"
    assert [hit.url for hit in response.hits] == ["https://example.com/1", "https://example.com/2"]
    assert response.hits[0].title == "标题1"
    assert response.hits[0].snippet == "摘要1"
    assert response.hits[0].published == "2026-09-01"
    assert response.hits[1].published is None
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {_KEY}"
    body = json.loads(request.content)
    assert body["query"] == "排序算法"
    assert body["max_results"] == 3
    assert body["search_depth"] == "basic"
    assert "time_range" not in body


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("days", "expected"), [(1, "day"), (7, "week"), (30, "month"), (365, "year"), (900, "year")]
)
async def test_search_maps_recency_days_to_time_range(days: int, expected: str) -> None:
    route = respx.post(f"{_BASE}/search").mock(
        return_value=httpx.Response(200, json=_search_payload())
    )
    await _provider().search("q", recency_days=days)
    assert json.loads(route.calls.last.request.content)["time_range"] == expected


@pytest.mark.asyncio
@respx.mock
async def test_search_clamps_max_results() -> None:
    route = respx.post(f"{_BASE}/search").mock(
        return_value=httpx.Response(200, json=_search_payload())
    )
    await _provider().search("q", max_results=500)
    assert json.loads(route.calls.last.request.content)["max_results"] == 20
    await _provider().search("q", max_results=0)
    assert json.loads(route.calls.last.request.content)["max_results"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_search_skips_items_without_url() -> None:
    respx.post(f"{_BASE}/search").mock(
        return_value=httpx.Response(
            200, json=_search_payload({"title": "无链接", "content": "x"}, _item(1))
        )
    )
    response = await _provider().search("q")
    assert [hit.url for hit in response.hits] == ["https://example.com/1"]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("query", ["", "   \n"])
async def test_search_rejects_blank_query_without_request(query: str) -> None:
    route = respx.post(f"{_BASE}/search").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(SearchError) as info:
        await _provider().search(query)
    assert not info.value.retryable
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_search_401_is_not_retried_and_message_hides_key() -> None:
    route = respx.post(f"{_BASE}/search").mock(
        return_value=httpx.Response(401, json={"detail": {"error": f"bad key {_KEY}"}})
    )
    with pytest.raises(SearchError) as info:
        await _provider().search("q")
    assert route.call_count == 1
    assert not info.value.retryable
    assert "TAVILY_API_KEY" in info.value.message
    assert _KEY not in info.value.message
    assert _KEY not in str(info.value)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status", [432, 433])
async def test_search_quota_errors_are_not_retried(status: int) -> None:
    route = respx.post(f"{_BASE}/search").mock(return_value=httpx.Response(status))
    with pytest.raises(SearchError) as info:
        await _provider().search("q")
    assert route.call_count == 1
    assert not info.value.retryable
    assert "额度" in info.value.message


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status", [400, 422])
async def test_search_bad_request_is_not_retried(status: int) -> None:
    route = respx.post(f"{_BASE}/search").mock(return_value=httpx.Response(status))
    with pytest.raises(SearchError) as info:
        await _provider().search("q")
    assert route.call_count == 1
    assert not info.value.retryable


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_search_retries_then_gives_up_with_retryable_error(status: int) -> None:
    route = respx.post(f"{_BASE}/search").mock(return_value=httpx.Response(status))
    with pytest.raises(SearchError) as info:
        await _provider(max_retries=2).search("q")
    assert route.call_count == 3
    assert info.value.retryable


@pytest.mark.asyncio
@respx.mock
async def test_search_recovers_after_transient_failure() -> None:
    route = respx.post(f"{_BASE}/search").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=_search_payload(_item(1)))]
    )
    response = await _provider().search("q")
    assert route.call_count == 2
    assert len(response.hits) == 1


@pytest.mark.asyncio
@respx.mock
async def test_search_timeout_is_retryable_error() -> None:
    route = respx.post(f"{_BASE}/search").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(SearchError) as info:
        await _provider(max_retries=1).search("q")
    assert route.call_count == 2
    assert info.value.retryable
    assert "超时" in info.value.message


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"query": "q"}),
        httpx.Response(200, json={"results": "oops"}),
    ],
)
async def test_search_malformed_response_is_error(response: httpx.Response) -> None:
    respx.post(f"{_BASE}/search").mock(return_value=response)
    with pytest.raises(SearchError) as info:
        await _provider().search("q")
    assert not info.value.retryable


@pytest.mark.asyncio
@respx.mock
async def test_extract_returns_text() -> None:
    route = respx.post(f"{_BASE}/extract").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [{"url": "https://example.com/1", "raw_content": "正文内容"}],
                "failed_results": [],
            },
        )
    )
    page = await _provider().extract("https://example.com/1", max_chars=100)
    assert page.url == "https://example.com/1"
    assert page.text == "正文内容"
    assert not page.truncated
    body = json.loads(route.calls.last.request.content)
    assert body["urls"] == ["https://example.com/1"]
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {_KEY}"


@pytest.mark.asyncio
@respx.mock
async def test_extract_truncates_long_text() -> None:
    respx.post(f"{_BASE}/extract").mock(
        return_value=httpx.Response(
            200, json={"results": [{"url": "https://e.com/", "raw_content": "字" * 500}]}
        )
    )
    page = await _provider().extract("https://e.com/", max_chars=100)
    assert page.truncated
    assert len(page.text) == 100
    assert page.total_chars == 500


@pytest.mark.asyncio
@respx.mock
async def test_extract_failed_result_is_error_with_reason() -> None:
    respx.post(f"{_BASE}/extract").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [],
                "failed_results": [{"url": "https://e.com/", "error": "Failed to fetch"}],
            },
        )
    )
    with pytest.raises(SearchError) as info:
        await _provider().extract("https://e.com/", max_chars=100)
    assert "https://e.com/" in info.value.message
    assert "Failed to fetch" in info.value.message
    assert not info.value.retryable


@pytest.mark.asyncio
@respx.mock
async def test_extract_empty_content_is_error() -> None:
    respx.post(f"{_BASE}/extract").mock(
        return_value=httpx.Response(
            200, json={"results": [{"url": "https://e.com/", "raw_content": "  "}]}
        )
    )
    with pytest.raises(SearchError):
        await _provider().extract("https://e.com/", max_chars=100)


@pytest.mark.asyncio
@respx.mock
async def test_extract_uses_same_error_mapping() -> None:
    respx.post(f"{_BASE}/extract").mock(return_value=httpx.Response(401))
    with pytest.raises(SearchError) as info:
        await _provider().extract("https://e.com/", max_chars=100)
    assert "TAVILY_API_KEY" in info.value.message


def test_build_search_provider_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        build_search_provider()


def test_build_search_provider_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    assert isinstance(build_search_provider(), TavilyProvider)
