"""`CancelToken`、`RuntimeFactory` 的最小单测（`stage.py`/`fake.py`/`bus.py`/
`tools.py` 已经通过各自的测试间接覆盖了 `runtime.py` 里的其余类型）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from studio.agent import events
from studio.agent.runtime import Budget, CancelToken, RuntimeFactory, TurnContext, UserInput
from studio.agent.tools import ToolContext
from studio.db.repo.profiles import ModelProfileValue
from studio.workspace.scope import WriteScope


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

    def test_has_reflects_registration(self) -> None:
        factory = RuntimeFactory()
        assert factory.has("fake") is False

        factory.register("fake", _StubRuntime)

        assert factory.has("fake") is True


def _record(relpath: str, sha256: str) -> None:
    return None


def test_tool_context_matches_turn_context(tmp_path: Path) -> None:
    profile = ModelProfileValue(
        id="p1",
        name="p",
        provider="fake",
        model="m",
        runtime="fake",
        base_url=None,
        api_key_env=None,
        supports_vision=False,
        price_input=None,
        price_output=None,
        max_cost_per_turn=None,
        max_steps_per_turn=None,
    )
    ctx = TurnContext(
        system_prompt="s",
        user_input=UserInput(text="hi"),
        tools=[],
        workdir=tmp_path,
        model_profile=profile,
        resume_ref=None,
        cancel_token=CancelToken(),
        budget=Budget(),
        write_scope=WriteScope(writable=["topic/**"], tool_managed=[]),
        project_id="proj-1",
        stage="topic",
        record_tool_write=_record,
    )

    assert ctx.tool_context() == ToolContext(
        project_id="proj-1", stage="topic", workdir=tmp_path, record_tool_write=_record
    )
