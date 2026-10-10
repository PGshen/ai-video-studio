"""模型连通性测试（`agent/probe.py`）：计时、超时、错误规整与打码。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

from studio.agent.oneshot import OneShotError
from studio.agent.probe import ERROR_MAX_CHARS, make_probe
from studio.db.repo.profiles import ModelProfileValue

_BASE = ModelProfileValue(
    id="p",
    name="p",
    provider="anthropic",
    model="m",
    runtime="claude",
    base_url=None,
    api_key_env=None,
    supports_vision=False,
    price_input=None,
    price_output=None,
    max_cost_per_turn=None,
    max_steps_per_turn=None,
)


class _Ask:
    """`ask_once` 的替身：记录调用，按设定返回文本、抛错或拖延。"""

    def __init__(
        self, reply: str | None = None, exc: BaseException | None = None, delay: float = 0.0
    ) -> None:
        self.reply = reply
        self.exc = exc
        self.delay = delay
        self.calls: list[ModelProfileValue] = []

    async def __call__(
        self, profile: ModelProfileValue, system: str, message: str, **kwargs: Any
    ) -> str:
        self.calls.append(profile)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc is not None:
            raise self.exc
        return self.reply or ""


async def test_success_reports_latency_and_reply(tmp_path: Path) -> None:
    probe = make_probe(tmp_path, environ={}, ask=_Ask("ok"))

    result = await probe(_BASE)

    assert result.ok is True
    assert result.reply == "ok"
    assert result.error is None
    assert result.latency_ms is not None and result.latency_ms >= 0


async def test_fake_runtime_succeeds_without_calling(tmp_path: Path) -> None:
    ask = _Ask("ok")
    probe = make_probe(tmp_path, environ={}, ask=ask)

    result = await probe(replace(_BASE, runtime="fake"))

    assert result.ok is True
    assert ask.calls == []


async def test_missing_key_fails_without_calling(tmp_path: Path) -> None:
    ask = _Ask("ok")
    probe = make_probe(tmp_path, environ={}, ask=ask)

    result = await probe(replace(_BASE, api_key_env="SOME_KEY"))

    assert result.ok is False
    assert result.latency_ms is None
    assert result.error is not None and "SOME_KEY" in result.error
    assert ask.calls == []


async def test_timeout(tmp_path: Path) -> None:
    probe = make_probe(tmp_path, environ={}, ask=_Ask("ok", delay=1.0), timeout=0.05)

    result = await probe(_BASE)

    assert result.ok is False
    assert result.error is not None and "超时" in result.error


async def test_empty_reply_is_failure(tmp_path: Path) -> None:
    probe = make_probe(tmp_path, environ={}, ask=_Ask("  "))

    result = await probe(_BASE)

    assert result.ok is False
    assert result.error is not None and "空" in result.error


async def test_error_is_reported(tmp_path: Path) -> None:
    probe = make_probe(tmp_path, environ={}, ask=_Ask(exc=OneShotError("model not found: m")))

    result = await probe(_BASE)

    assert result.ok is False
    assert result.latency_ms is not None
    assert result.error == "model not found: m"


async def test_error_without_message_uses_exception_type(tmp_path: Path) -> None:
    probe = make_probe(tmp_path, environ={}, ask=_Ask(exc=ConnectionError()))

    result = await probe(_BASE)

    assert result.error == "ConnectionError"


async def test_error_hides_key_and_base_url_credentials(tmp_path: Path) -> None:
    profile = replace(
        _BASE, api_key_env="MY_KEY", base_url="https://alice:pw-secret@gw.example.com/v1"
    )
    message = "401 for sk-live-123 at https://alice:pw-secret@gw.example.com/v1 " + "x" * 500
    probe = make_probe(
        tmp_path, environ={"MY_KEY": "sk-live-123"}, ask=_Ask(exc=RuntimeError(message))
    )

    result = await probe(profile)

    assert result.error is not None
    assert "sk-live-123" not in result.error
    assert "pw-secret" not in result.error
    assert "alice" not in result.error
    assert len(result.error) <= ERROR_MAX_CHARS


async def test_long_reply_is_truncated(tmp_path: Path) -> None:
    probe = make_probe(tmp_path, environ={}, ask=_Ask("好" * 500))

    result = await probe(_BASE)

    assert result.ok is True
    assert result.reply is not None and len(result.reply) <= 100
