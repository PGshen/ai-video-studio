"""各阶段的提示词、专属工具、产物 schema、定稿逻辑（设计 §5；ARCHITECTURE §2）。

M1 只有 `topic`/`narrative`/`animation` 的占位定义（占位提示词 + §4.3 的
可写范围，没有业务工具）；`brainstorm` 不在 M1 范围内。这些占位定义不会
自动注册到任何地方——`main`（T7 之后）负责实例化并注册进
`studio.agent.stage.StageRegistry`。
"""

from __future__ import annotations
