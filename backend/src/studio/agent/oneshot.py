"""单轮、不带工具的一次性模型调用：会话自动命名和模型连通性测试共用。

按模型配置的运行时分派：`claude` 用 Claude Agent SDK 的 `query()`，`openai` 用 Agents SDK
的 `Runner.run`；其它运行时（`fake`）不支持。不进会话的轮次/事件，也不算进会话成本。
调用失败（SDK 抛错、Claude 的 result 或助手消息带错误）抛 `OneShotError` 或原异常；
超时由调用方用 `asyncio.wait_for` 控制。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from contextlib import aclosing
from pathlib import Path
from typing import Any, cast

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from studio.agent.claude_env import build_env
from studio.db.repo.profiles import ModelProfileValue

SUPPORTED_RUNTIMES = frozenset({"claude", "openai"})


class OneShotError(Exception):
    """模型调用没有拿到正常回复；消息是给人看的简短原因。"""


async def _claude(
    profile: ModelProfileValue,
    system: str,
    message: str,
    data_dir: Path,
    environ: Mapping[str, str],
    workdir: str,
) -> str:
    claude_dir = data_dir / "claude"
    _auth, env = build_env(profile.api_key_env, profile.base_url, environ, claude_dir)
    cwd = claude_dir / workdir
    cwd.mkdir(parents=True, exist_ok=True)
    options = ClaudeAgentOptions(
        model=profile.model,
        cwd=cwd,
        system_prompt=system,
        tools=[],
        setting_sources=[],
        max_turns=1,
        env=env,
        thinking={"type": "disabled"},
        verbatim_prompts=True,
    )
    parts: list[str] = []
    # `async for` does not close the generator when the body raises; close it here so the
    # CLI subprocess is shut down in this task rather than whenever GC gets to it.
    # `query()` is annotated as AsyncIterator but is an async generator at runtime.
    stream = cast(AsyncGenerator[Any, None], query(prompt=message, options=options))
    async with aclosing(stream):
        async for item in stream:
            if isinstance(item, AssistantMessage):
                text = "".join(b.text for b in item.content if isinstance(b, TextBlock))
                if item.error:
                    raise OneShotError(f"{item.error}: {text}" if text else item.error)
                parts.append(text)
            elif isinstance(item, ResultMessage) and item.is_error:
                raise OneShotError("; ".join(item.errors or []) or item.result or item.subtype)
    return "".join(parts)


async def _openai(
    profile: ModelProfileValue, system: str, message: str, environ: Mapping[str, str]
) -> str:
    from agents import Agent, RunConfig, Runner

    from studio.agent.openai_runtime import _api_key, _check_provider, build_model

    _check_provider(profile)
    agent = Agent(
        name="oneshot",
        instructions=system,
        model=build_model(profile, _api_key(profile, environ)),
    )
    result = await Runner.run(
        agent, message, max_turns=1, run_config=RunConfig(tracing_disabled=True)
    )
    return str(result.final_output or "")


async def ask_once(
    profile: ModelProfileValue,
    system: str,
    message: str,
    *,
    data_dir: Path,
    environ: Mapping[str, str],
    workdir: str,
) -> str:
    """用 `profile` 问一次，返回文本回复。`workdir`：Claude CLI 在数据目录下的工作目录名。"""
    if profile.runtime == "claude":
        return await _claude(profile, system, message, data_dir, environ, workdir)
    if profile.runtime == "openai":
        return await _openai(profile, system, message, environ)
    raise OneShotError(f"运行时 {profile.runtime} 不支持单轮调用")
