"""单轮无工具调用（`agent/oneshot.py`）：按运行时分派、收集文本、把失败的 result 转成异常。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from studio.agent import oneshot
from studio.agent.oneshot import OneShotError, ask_once
from studio.db.repo.profiles import ModelProfileValue


def _profile(runtime: str, *, api_key_env: str | None = None) -> ModelProfileValue:
    return ModelProfileValue(
        id="p",
        name="p",
        provider="anthropic" if runtime == "claude" else "openai",
        model="m",
        runtime=runtime,
        base_url=None,
        api_key_env=api_key_env,
        supports_vision=False,
        price_input=None,
        price_output=None,
        max_cost_per_turn=None,
        max_steps_per_turn=None,
    )


def _result(*, is_error: bool, errors: list[str] | None = None) -> ResultMessage:
    return ResultMessage(
        subtype="error_during_execution" if is_error else "success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="s",
        errors=errors,
    )


def _fake_query(messages: list[Any], seen: dict[str, Any]) -> Any:
    async def query(*, prompt: str, options: Any) -> AsyncIterator[Any]:
        seen["prompt"] = prompt
        seen["options"] = options
        for message in messages:
            yield message

    return query


async def test_claude_collects_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    messages = [
        AssistantMessage(content=[TextBlock("o"), TextBlock("k")], model="m"),
        _result(is_error=False),
    ]
    monkeypatch.setattr(oneshot, "query", _fake_query(messages, seen))

    text = await ask_once(
        _profile("claude"), "系统", "你好", data_dir=tmp_path, environ={}, workdir="probe"
    )

    assert text == "ok"
    assert seen["prompt"] == "你好"
    assert seen["options"].system_prompt == "系统"
    assert seen["options"].tools == []
    assert seen["options"].max_turns == 1
    assert seen["options"].cwd == tmp_path / "claude" / "probe"


async def test_claude_error_result_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    messages = [_result(is_error=True, errors=["API Error: 401 invalid x-api-key"])]
    monkeypatch.setattr(oneshot, "query", _fake_query(messages, {}))

    with pytest.raises(OneShotError, match="401"):
        await ask_once(_profile("claude"), "s", "m", data_dir=tmp_path, environ={}, workdir="w")


async def test_claude_assistant_error_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    messages = [
        AssistantMessage(content=[TextBlock("Invalid model")], model="m", error="invalid_request"),
        _result(is_error=False),
    ]
    monkeypatch.setattr(oneshot, "query", _fake_query(messages, {}))

    with pytest.raises(OneShotError, match="invalid_request"):
        await ask_once(_profile("claude"), "s", "m", data_dir=tmp_path, environ={}, workdir="w")


async def test_openai_runs_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from agents import Runner

    seen: dict[str, Any] = {}

    class _Result:
        final_output = "ok"

    async def run(agent: Any, message: str, **kwargs: Any) -> _Result:
        seen["instructions"] = agent.instructions
        seen["message"] = message
        seen["max_turns"] = kwargs["max_turns"]
        return _Result()

    monkeypatch.setattr(Runner, "run", run)

    text = await ask_once(
        _profile("openai", api_key_env="K"),
        "系统",
        "你好",
        data_dir=tmp_path,
        environ={"K": "sk-test"},
        workdir="w",
    )

    assert text == "ok"
    assert seen == {"instructions": "系统", "message": "你好", "max_turns": 1}


async def test_unsupported_runtime_raises(tmp_path: Path) -> None:
    with pytest.raises(OneShotError, match="fake"):
        await ask_once(_profile("fake"), "s", "m", data_dir=tmp_path, environ={}, workdir="w")
