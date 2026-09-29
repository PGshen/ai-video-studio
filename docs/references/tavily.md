# Tavily（联网搜索与网页抓取）

## ✅ 已验证：搜索与抓取的端点、字段、错误码

日期：2026-09-29（M4 T1）。来源：Tavily 官方文档
（`docs.tavily.com/documentation/api-reference/endpoint/search`、`.../extract`）。
代码：`backend/src/studio/search/tavily.py`。

| 项 | 内容 |
|---|---|
| 鉴权 | 两个端点都是 `POST`，请求头 `Authorization: Bearer tvly-...` |
| 搜索 | `POST https://api.tavily.com/search`；`query`（必填）、`search_depth`（`basic`/`fast`/`ultra-fast` 各 1 credit，`advanced` 2 credit）、`max_results`（0–20，默认 10）、`time_range`（`day`/`week`/`month`/`year`）、`include_published_date`（`topic=news` 时自动开启）等 |
| 搜索响应 | `{query, results: [{title, url, content, score, published_date?, raw_content?}], response_time, request_id}` |
| 抓取 | `POST https://api.tavily.com/extract`；`urls`（1–20 个）、`extract_depth`（`basic`/`advanced`）、`format`（`markdown`/`text`）、`timeout`（1–60 秒） |
| 抓取响应 | `{results: [{url, raw_content}], failed_results: [{url, error}], response_time}`；HTTP 200 时要同时看 `results` 和 `failed_results` |
| 错误码 | 400/422 参数错误；401 key 缺失或无效；429 限流（带 `Retry-After`）；432 key 或套餐额度用尽；433 按量付费额度用尽；500 服务端错误 |

本项目的用法：`search` 固定 `search_depth=basic`、`include_published_date=true`，
`recency_days` 映射到 `time_range`（≤1 天 `day`、≤7 `week`、≤31 `month`，其余 `year`）；
`extract` 固定 `format=markdown`、`extract_depth=basic`，每次一个 URL，正文在本地按
`max_chars` 截断。只重试 429、5xx 和超时/网络错误；432/433 视为额度问题，不重试。

## ⚠️ 待验证

真实调用的延迟、`extract` 对常见站点（维基百科、博客、新闻站）的表现——M4 T13 冒烟后补。
