"""会话自动命名：让会话自己的模型把第一条用户消息概括成一个 10 字以内的标题。

一次性、不带工具的单轮调用，不进会话的轮次/事件，也不算进会话成本（用量极小）。
按会话模型配置的运行时分派：`claude` 用 Claude Agent SDK 的 `query()`，`openai` 用 Agents SDK
的 `Runner.run`；其它运行时（`fake`）不支持，返回 `None`，调用方保留从消息截取的临时标题。
任何失败都只返回 `None`（记日志），命名是锦上添花，不能影响对话。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from studio.agent.claude_env import build_env
from studio.db.repo.profiles import ModelProfileValue

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 10
TITLE_TIMEOUT_SECONDS = 60.0

TitleGenerator = Callable[[ModelProfileValue, str], Awaitable[str | None]]
"""`(会话的模型配置, 第一条用户消息) → 标题或 None`。"""

INSTRUCTIONS = (
    f"你是会话命名助手。根据用户的第一条消息，用不超过 {TITLE_MAX_CHARS} 个汉字"
    "（英文则不超过 4 个单词）概括这次对话要做的事，作为会话标题。"
    "只输出标题本身：不要引号、标点、前缀（如「标题：」）和解释。"
)
_MAX_INPUT_CHARS = 1000
_WRAPPERS = "\"'“”‘’「」『』《》【】[]()（）"
_TRAILING_PUNCT = "。.，,！!？?；;：:、…"


def clean_title(raw: str | None) -> str | None:
    """规整模型输出：第一个非空行，去「标题：」前缀、首尾引号和句末标点，截到 `TITLE_MAX_CHARS`。"""
    if not raw:
        return None
    line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    line = re.sub(r"^(?:会话)?标题\s*[:：]\s*", "", line)
    line = line.strip(_WRAPPERS + " ").rstrip(_TRAILING_PUNCT + " ").strip(_WRAPPERS + " ")
    if not line:
        return None
    return line if len(line) <= TITLE_MAX_CHARS else line[:TITLE_MAX_CHARS]


async def _claude_title(
    profile: ModelProfileValue, message: str, data_dir: Path, environ: Mapping[str, str]
) -> str | None:
    claude_dir = data_dir / "claude"
    _auth, env = build_env(profile.api_key_env, profile.base_url, environ, claude_dir)
    cwd = claude_dir / "titler"
    cwd.mkdir(parents=True, exist_ok=True)
    options = ClaudeAgentOptions(
        model=profile.model,
        cwd=cwd,
        system_prompt=INSTRUCTIONS,
        tools=[],
        setting_sources=[],
        max_turns=1,
        env=env,
        thinking={"type": "disabled"},
        verbatim_prompts=True,
    )
    parts: list[str] = []
    async for item in query(prompt=message, options=options):
        if isinstance(item, AssistantMessage):
            parts.extend(block.text for block in item.content if isinstance(block, TextBlock))
    return "".join(parts)


async def _openai_title(
    profile: ModelProfileValue, message: str, environ: Mapping[str, str]
) -> str | None:
    from agents import Agent, RunConfig, Runner

    from studio.agent.openai_runtime import _api_key, _check_provider, build_model

    _check_provider(profile)
    agent = Agent(
        name="session-titler",
        instructions=INSTRUCTIONS,
        model=build_model(profile, _api_key(profile, environ)),
    )
    result = await Runner.run(
        agent, message, max_turns=1, run_config=RunConfig(tracing_disabled=True)
    )
    return str(result.final_output or "")


def make_title_generator(
    data_dir: Path, environ: Mapping[str, str] | None = None
) -> TitleGenerator:
    env = environ if environ is not None else os.environ

    async def generate(profile: ModelProfileValue, message: str) -> str | None:
        text = message.strip()[:_MAX_INPUT_CHARS]
        try:
            if profile.runtime == "claude":
                coro = _claude_title(profile, text, data_dir, env)
            elif profile.runtime == "openai":
                coro = _openai_title(profile, text, env)
            else:
                return None
            return clean_title(await asyncio.wait_for(coro, TITLE_TIMEOUT_SECONDS))
        except Exception:
            logger.warning("会话自动命名失败（沿用截取的标题）", exc_info=True)
            return None

    return generate
