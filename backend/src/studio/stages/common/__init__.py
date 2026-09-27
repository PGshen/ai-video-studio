"""各阶段共用代码（设计 §4.3 表格；ARCHITECTURE §2）。

M1 只提供占位阶段定义（`stages.topic`/`stages.narrative`/`stages.animation`），
还没有需要跨阶段共享的业务逻辑（例如 `suggest_upstream_change`），所以这个
包暂时是空的；`stages.<x>` 之间互不 import（ARCHITECTURE §2 规则 3），共用
代码之后加进来时放在这里。
"""

from __future__ import annotations
