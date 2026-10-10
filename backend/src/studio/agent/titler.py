"""会话自动命名：让会话自己的模型把第一条用户消息概括成一个 10 字以内的标题。

一次性、不带工具的单轮调用（`agent/oneshot.py`），不算进会话成本（用量极小）。
`fake` 等不支持的运行时返回 `None`，调用方保留从消息截取的临时标题。
任何失败都只返回 `None`（记日志），命名是锦上添花，不能影响对话。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from studio.agent.oneshot import SUPPORTED_RUNTIMES, ask_once
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


def make_title_generator(
    data_dir: Path, environ: Mapping[str, str] | None = None
) -> TitleGenerator:
    env = environ if environ is not None else os.environ

    async def generate(profile: ModelProfileValue, message: str) -> str | None:
        text = message.strip()[:_MAX_INPUT_CHARS]
        try:
            if profile.runtime not in SUPPORTED_RUNTIMES:
                return None
            coro = ask_once(
                profile, INSTRUCTIONS, text, data_dir=data_dir, environ=env, workdir="titler"
            )
            return clean_title(await asyncio.wait_for(coro, TITLE_TIMEOUT_SECONDS))
        except Exception:
            logger.warning("会话自动命名失败（沿用截取的标题）", exc_info=True)
            return None

    return generate
