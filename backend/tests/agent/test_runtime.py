"""`CancelToken`、`RuntimeFactory` 的最小单测（`stage.py`/`fake.py`/`bus.py`/
`tools.py` 已经通过各自的测试间接覆盖了 `runtime.py` 里的其余类型）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from studio.agent import events
from studio.agent.runtime import CancelToken, RuntimeFactory, TurnContext


class _StubRuntime:
    """满足 `AgentRuntime` 协议的最小实现，只用来验证 `RuntimeFactory`
    按注册的构造函数返回实例，不关心 `run_turn` 的实际行为。
    """

    async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
        return
        yield  # pragma: no cover -- 让方法成为异步生成器，永远不会执行到


class TestCancelToken:
    def test_starts_not_cancelled(self) -> None:
        token = CancelToken()
        assert token.is_cancelled is False

    def test_cancel_sets_flag(self) -> None:
        token = CancelToken()
        token.cancel()
        assert token.is_cancelled is True

    async def test_wait_returns_immediately_once_cancelled(self) -> None:
        token = CancelToken()
        token.cancel()
        await asyncio.wait_for(token.wait(), timeout=0.1)


class TestRuntimeFactory:
    def test_create_returns_instance_from_registered_constructor(self) -> None:
        factory = RuntimeFactory()
        sentinel = _StubRuntime()
        factory.register("fake", lambda: sentinel)

        assert factory.create("fake") is sentinel

    def test_create_unregistered_name_raises_key_error(self) -> None:
        factory = RuntimeFactory()

        with pytest.raises(KeyError):
            factory.create("claude")
