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

## ✅ 已验证：真实调用的表现

日期：2026-09-29（M4 T13 冒烟 + T12 走查）。来源：实测，`make smoke SMOKE_ARGS="-k tavily"`
（`backend/tests/smoke/test_smoke.py::test_tavily_search`），证据在 `data/evidence/m4-topic/smoke/`（不进 git）。

| 观察 | 值 |
|---|---|
| `search`（`basic`、3 条） | 约 2.1 秒；每条有 `title`/`url`/`content`（摘要 500–1200 字）；技术博客类结果带 `published_date`（RFC 2822 格式，如 `Fri, 30 Jan 2026 00:00:00 GMT`），部分站点没有，字段缺省 |
| `extract`（一个 URL、`markdown`） | 约 1.1 秒；一篇技术博客返回 10196 字正文，本地按 `max_chars=2000` 截断；成功时结果里 `raw_content` 是 Markdown，链接保留 |
| 真实模型使用（T12/T13，Claude 登录） | 选题阶段一轮 9–16 步里 2–4 次搜索、2–3 次抓取，Tavily 免费额度消耗很小；模型偶尔尝试读没搜索过的 URL，被「URL 来源」规则拒绝后会改为先搜索 |

`SearchHit.published` 只是把 `published_date` 原样当字符串保留，没有解析成日期（模型只是阅读它）。
