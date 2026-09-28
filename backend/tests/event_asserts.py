"""TD-10：完整一轮事件流的断言辅助——断言相对顺序和不变量，而不是绑定完整
的事件类型列表。

`agent/runner.py` 按 T6/T7 拆分模块时，事件之间真正有因果关系的顺序（比如
`tool_result` 必须先于它触发的 `workspace_changed`）不会变，但两个互相没有
因果关系的事件谁先发布只是实现细节，不应该让测试跟着同步改。

给 `tests/api/test_stream.py`（SSE 帧的 `event` 字段）和
`tests/agent/test_runner.py`（持久化事件的 `type` 字段）共用；两边都从这个
文件所在的 `tests/` 目录被 pytest 加进 `sys.path`（`tests/` 本身没有
`__init__.py`，两个子包 `tests/api`、`tests/agent` 各自独立顶层导入），所以
直接 `from event_asserts import ...` 即可，不需要相对导入。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence


def assert_in_order[T](sequence: Sequence[T], *items: T) -> None:
    """断言 `items` 依次（允许中间插入其它元素）出现在 `sequence` 里——即
    `items` 是 `sequence` 的一个子序列。

    用来表达"A 必须在 B 之前发生"这类真正的因果不变量：A、B 之间可以有任何
    和这条不变量无关的事件，不要求它们紧挨着、也不要求 `sequence` 里只有
    这些元素。
    """
    remaining = list(items)
    for value in sequence:
        if remaining and value == remaining[0]:
            remaining.pop(0)
            if not remaining:
                return
    raise AssertionError(
        f"expected {list(items)!r} to appear in order (as a subsequence) of "
        f"{list(sequence)!r}; stuck at {remaining!r}"
    )


def type_counts[T](sequence: Iterable[T]) -> Counter[T]:
    """按类型分组计数：只断言"每种事件发生了几次"，不关心彼此的先后顺序。"""
    return Counter(sequence)
