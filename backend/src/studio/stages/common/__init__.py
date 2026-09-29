"""各阶段共用代码（设计 §4.3 表格；ARCHITECTURE §2）。

`suggest_upstream_change`（设计 §5.3/§5.4）是第一个共用业务工具：任意阶段
都可能需要向上游提出回退建议，逻辑只写一份，放在这里；`stages.<x>` 之间
互不 import（ARCHITECTURE §2 规则 3）。
"""

from __future__ import annotations

from studio.stages.common.suggest_upstream_change import (
    SUGGEST_UPSTREAM_CHANGE_TOOL,
    SuggestUpstreamChangeArgs,
)
from studio.stages.common.web_tools import FETCH_URL_TOOL, WEB_SEARCH_TOOL

__all__ = [
    "FETCH_URL_TOOL",
    "SUGGEST_UPSTREAM_CHANGE_TOOL",
    "SuggestUpstreamChangeArgs",
    "WEB_SEARCH_TOOL",
]
