"""Claude SDK 消息与本项目事件之间的转换（从 `claude_runtime` 拆出）。

- 输入：`UserInput` → SDK prompt（带图片时走流式输入）；业务 `ToolSpec` → 进程内 MCP 工具。
- 输出：SDK 消息 → `events.AgentEvent`，同时在 `SdkTurn` 上记下 SDK 会话 id；
  子 agent 的消息丢弃，业务工具名去掉 `mcp__studio__` 前缀。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    Message,
    ResultMessage,
    SdkMcpTool,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from studio.agent import events
from studio.agent.runtime import TurnContext, UserInput
from studio.agent.tools import ToolSpec, invoke_tool

logger = logging.getLogger(__name__)

MCP_SERVER_NAME = "studio"
MCP_PREFIX = f"mcp__{MCP_SERVER_NAME}__"


def build_sdk_tool(spec: ToolSpec, ctx: TurnContext) -> SdkMcpTool[Any]:
    """把业务 `ToolSpec` 转成 SDK 的进程内 MCP 工具；调用统一走 `invoke_tool`。"""
    tool_ctx = ctx.tool_context()

    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        result = await invoke_tool(spec, tool_ctx, args)
        content: list[dict[str, Any]] = [{"type": "text", "text": result.text}]
        content += [
            {"type": "image", "data": image.data_base64, "mimeType": image.media_type}
            for image in result.images
        ]
        return {"content": content, "is_error": result.is_error}

    return SdkMcpTool(
        name=spec.name,
        description=spec.description,
        input_schema=spec.input_model.model_json_schema(),
        handler=handler,
    )


def prompt_input(user_input: UserInput) -> str | AsyncIterable[dict[str, Any]]:
    if not user_input.images:
        return user_input.text

    async def stream() -> AsyncIterator[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_input.text}]
        content += [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.media_type,
                    "data": image.data_base64,
                },
            }
            for image in user_input.images
        ]
        yield {
            "type": "user",
            "message": {"role": "user", "content": content},
            "parent_tool_use_id": None,
        }

    return stream()


def _tool_result_content(
    content: str | list[dict[str, Any]] | None,
) -> tuple[str, list[events.ImageData]]:
    if content is None:
        return "", []
    if isinstance(content, str):
        return content, []
    texts: list[str] = []
    images: list[events.ImageData] = []
    for block in content:
        kind = block.get("type")
        if kind == "text":
            texts.append(str(block.get("text", "")))
        elif kind == "image":
            source = block.get("source")
            if isinstance(source, dict):  # Anthropic API shape
                media_type, data = source.get("media_type"), source.get("data")
            else:  # MCP shape
                media_type, data = block.get("mimeType"), block.get("data")
            if isinstance(media_type, str) and isinstance(data, str):
                images.append(events.ImageData(media_type, data))
            else:
                logger.warning("跳过缺少 media type 或数据的图片块：%s", sorted(block))
    return "\n".join(texts), images


@dataclass
class SdkTurn:
    session_id: str | None
    queried: bool = False
    interrupted: bool = False
    result: ResultMessage | None = None


def convert_message(message: Message, turn: SdkTurn) -> list[events.AgentEvent]:
    if isinstance(message, SystemMessage):
        session_id = message.data.get("session_id")
        if isinstance(session_id, str):
            turn.session_id = session_id
        return []
    if isinstance(message, StreamEvent | AssistantMessage | ResultMessage) and message.session_id:
        turn.session_id = message.session_id
    if isinstance(message, StreamEvent | AssistantMessage | UserMessage):
        if message.parent_tool_use_id is not None:
            return []  # subagent traffic
    if isinstance(message, StreamEvent):
        event = message.event
        delta = event.get("delta") or {}
        if event.get("type") == "content_block_delta":
            if delta.get("type") == "text_delta":
                return [events.TextDelta(text=delta.get("text", ""))]
            if delta.get("type") == "thinking_delta" and delta.get("thinking"):
                return [events.ThinkingDelta(text=delta["thinking"])]
        return []
    converted: list[events.AgentEvent] = []
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, ThinkingBlock):
                if block.thinking.strip():  # `signature` is for replay only, never forwarded
                    converted.append(events.ThinkingBlock(text=block.thinking))
            elif isinstance(block, TextBlock) and block.text:
                converted.append(events.TextBlock(text=block.text))
            elif isinstance(block, ToolUseBlock):
                name = block.name.removeprefix(MCP_PREFIX)
                converted.append(events.ToolCall(call_id=block.id, name=name, args=block.input))
    elif isinstance(message, UserMessage) and isinstance(message.content, list):
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                text, images = _tool_result_content(block.content)
                converted.append(
                    events.ToolResult(
                        call_id=block.tool_use_id,
                        text=text,
                        images=images,
                        is_error=bool(block.is_error),
                    )
                )
    return converted
