"""`STUDIO_WEB_MODE=native` 时 Claude 原生 `WebFetch` 的「URL 来源」限制（TD-39，ADR 0010）。

自建 `fetch_url` 只抓本会话搜索结果或用户消息里的 URL（`url_source`）。原生模式下搜索发生在
CLI 内部，所以用两个 hook 把同一条规则接上：

- `PostToolUse(WebSearch)`：把搜索结果里出现的 URL 记入本会话的集合。为了不依赖 CLI 返回值的
  具体结构，直接对序列化后的 `tool_response` 做 URL 提取；
- `PreToolUse(WebFetch)`：目标 URL 本身必须是公开网页地址（不是 IP、内网、带账号密码），
  且必须在本会话允许集合里，否则拒绝。

只有 `WebSearch`/`WebFetch` 这条路径受限；`native` 模式的其他风险（搜索词本身会发给搜索服务）不变。
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk.types import HookCallback, HookContext, HookInput, HookJSONOutput
from sqlalchemy import Engine

from studio.agent import url_source

WEB_FETCH_TOOL = "WebFetch"
WEB_SEARCH_TOOL = "WebSearch"


def _deny(reason: str) -> HookJSONOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def fetch_denial_reason(engine: Engine | None, session_id: str | None, url: object) -> str | None:
    """`WebFetch` 的目标 URL 不允许抓取时返回原因，否则 `None`。"""
    if not isinstance(url, str) or not url.strip():
        return "无法确定要读取的地址，已拒绝。"
    reason = url_source.refusal_reason(url)
    if reason is not None:
        return f"不能读取这个地址：{reason}。"
    if url_source.normalize_url(url) not in url_source.allowed_urls(engine, session_id):
        return (
            "这个地址不在本会话的搜索结果或用户消息里，不能读取。"
            "请先用 WebSearch 找到它，或请用户把链接贴出来。"
        )
    return None


def web_fetch_hook(engine: Engine | None, session_id: str | None) -> HookCallback:
    async def hook(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}
        tool_input: dict[str, Any] = input_data["tool_input"]
        reason = fetch_denial_reason(engine, session_id, tool_input.get("url"))
        return {} if reason is None else _deny(reason)

    return hook


def web_search_collect_hook(session_id: str | None) -> HookCallback:
    async def hook(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PostToolUse" or session_id is None:
            return {}
        response = json.dumps(input_data["tool_response"], ensure_ascii=False, default=str)
        url_source.record_searched(session_id, url_source.urls_in(response))
        return {}

    return hook
