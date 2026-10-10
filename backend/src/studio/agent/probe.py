"""模型连通性测试：用一份模型配置真的发一次极小的请求，报告成败、耗时和简短原因。

走和会话自动命名相同的单轮调用（`agent/oneshot.py`），能同时验证 base_url、密钥、模型名
和运行时（Claude 还包括 CLI 本身）整条链路。`fake` 运行时不发请求，直接成功。
不算进任何会话的成本（用量极小）。错误信息里去掉密钥的值和 base_url 里的账号密码，并截断。
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from studio.agent.oneshot import ask_once
from studio.db.repo.profiles import ModelProfileValue

PROBE_TIMEOUT_SECONDS = 30.0
ERROR_MAX_CHARS = 300
REPLY_MAX_CHARS = 100

INSTRUCTIONS = "这是连通性测试。只回复 ok 两个字母，不要输出其他内容。"
MESSAGE = "ping"


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: int | None
    reply: str | None
    error: str | None


Probe = Callable[[ModelProfileValue], Awaitable[ProbeResult]]
Ask = Callable[..., Awaitable[str]]


def _secrets(profile: ModelProfileValue, environ: Mapping[str, str]) -> list[str]:
    found: list[str] = []
    if profile.api_key_env and environ.get(profile.api_key_env):
        found.append(environ[profile.api_key_env])
    if profile.base_url:
        parts = urlsplit(profile.base_url)
        for value in (parts.password, parts.username):
            if value:
                found.extend({value, unquote(value)})
    # Longest first so a password that contains the username is removed whole.
    return sorted(found, key=len, reverse=True)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _describe(exc: BaseException, secrets: list[str]) -> str:
    text = str(exc).strip() or type(exc).__name__
    for secret in secrets:
        text = text.replace(secret, "***")
    return _clip(text, ERROR_MAX_CHARS)


def _fail(error: str, latency_ms: int | None = None) -> ProbeResult:
    return ProbeResult(ok=False, latency_ms=latency_ms, reply=None, error=error)


def make_probe(
    data_dir: Path,
    environ: Mapping[str, str] | None = None,
    *,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    ask: Ask = ask_once,
) -> Probe:
    env = environ if environ is not None else os.environ

    async def probe(profile: ModelProfileValue) -> ProbeResult:
        if profile.runtime == "fake":
            return ProbeResult(ok=True, latency_ms=0, reply="fake 运行时不发请求", error=None)
        if profile.api_key_env and not env.get(profile.api_key_env):
            return _fail(f"环境变量 {profile.api_key_env} 未设置（写在 backend/.env 后重启）")
        start = time.monotonic()
        try:
            reply = await asyncio.wait_for(
                ask(
                    profile, INSTRUCTIONS, MESSAGE, data_dir=data_dir, environ=env, workdir="probe"
                ),
                timeout,
            )
        except TimeoutError:
            return _fail(f"超时：{timeout:g} 秒内没有回复", round(timeout * 1000))
        except Exception as exc:
            elapsed = round((time.monotonic() - start) * 1000)
            return _fail(_describe(exc, _secrets(profile, env)), elapsed)
        elapsed = round((time.monotonic() - start) * 1000)
        reply = reply.strip()
        if not reply:
            return _fail("模型返回了空回复", elapsed)
        return ProbeResult(
            ok=True, latency_ms=elapsed, reply=_clip(reply, REPLY_MAX_CHARS), error=None
        )

    return probe
