"""选题简报测试的共用构造器（计划 M4 T6）。"""

from __future__ import annotations

from pathlib import Path

from studio.stages.topic.brief import SECTIONS

FIXTURE = Path(__file__).parent / "fixtures" / "narrative" / "brief.md"

_GOOD_BODIES = {
    "核心问题": "为什么排序算法能在一秒内处理十亿条记录？",
    "钩子与反直觉点": "多数人以为排序很慢，其实分治把复杂度压到 O(n log n)。",
    "目标观众与前置知识": "了解基本数据结构的程序员。",
    "关键事实": "- 归并排序是 O(n log n)（出处：https://example.com/merge；把握程度：高）",
    "叙事角度与结构草图": "先抛悬念，再讲分治，最后举例。",
    "可视化机会": "方块不断分裂又合并。",
    "风险点": "分治对零基础观众仍然抽象，需要用具体例子兜底，避免一上来就讲递归。",
}


def make_brief(**overrides: str | None) -> str:
    bodies = {**_GOOD_BODIES, **overrides}
    parts = ["# 选题简报\n"]
    for name in SECTIONS:
        body = bodies[name]
        if body is None:
            continue
        parts.append(f"## {name}\n\n{body}\n")
    return "\n".join(parts)
