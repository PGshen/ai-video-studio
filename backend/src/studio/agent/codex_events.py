"""`codex exec --json` 事件 → `AgentEvent`（codex-runtime T3；格式见 docs/references/codex.md）。

- `agent_message` → `TextBlock`；`reasoning` → `ThinkingBlock`（exec 模式没有增量事件）。
- `command_execution` → `shell`、`file_change` → `apply_patch`、`mcp_tool_call` → 业务工具名；
  `item.started` 产出 `ToolCall`、`item.completed` 产出 `ToolResult`（没见到 started 时先补
  `ToolCall`）。`call_id` 加本轮前缀：codex 的 item id 每次进程都从 `item_0` 数起。
- `turn.started` 之前的 `error` item 是配置警告（未识别的键、模型元数据缺失），产出
  `Notice(runtime_warning)` 让用户看到——桌面版 CLI 自动升级后参数失效时靠它发现；之后的
  `error` item 和顶层 `error` 事件（重连等）只记日志，本轮成败只看 `turn.completed`/`turn.failed`。
- 没见过的 item 类型（例如关不掉的多 agent 协作工具）每种提示一次；`todo_list` 忽略。
- `turn.completed.usage` 是会话累计值，原样存进 `CodexTurn.usage`，由运行时求差。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio.agent import events

logger = logging.getLogger(__name__)

WARNING_KIND = "runtime_warning"
_IGNORED_ITEMS = frozenset({"todo_list"})
_FAILURE_LIMIT = 500
_AUTH_HINT = "Codex 未登录或登录已失效：请在终端运行 codex login（选 ChatGPT 登录）后重试。"
_AUTH_MARKERS = ("401 Unauthorized", "Missing bearer", "invalid_api_key", "Incorrect API key")


@dataclass
class CodexTurn:
    """一次 `codex exec` 进程的解析状态。"""

    workdir: Path
    call_prefix: str
    thread_id: str | None = None
    turn_started: bool = False
    usage: dict[str, int] | None = None
    """`turn.completed.usage`（会话累计值）。"""
    failure: str | None = None
    """`turn.failed.error.message` 原文。"""
    _open_calls: set[str] = field(default_factory=set)
    _warned_types: set[str] = field(default_factory=set)


def convert_event(obj: Mapping[str, Any], turn: CodexTurn) -> list[events.AgentEvent]:
    kind = obj.get("type")
    if kind == "thread.started":
        turn.thread_id = str(obj.get("thread_id") or "") or turn.thread_id
    elif kind == "turn.started":
        turn.turn_started = True
    elif kind == "turn.completed":
        raw = obj.get("usage") or {}
        turn.usage = {key: int(value or 0) for key, value in raw.items()}
    elif kind == "turn.failed":
        error = obj.get("error") or {}
        turn.failure = str(error.get("message") or "codex 报告本轮失败")
    elif kind == "error":
        logger.info("codex: %s", _clip(str(obj.get("message")), _FAILURE_LIMIT))
    elif kind in ("item.started", "item.updated", "item.completed"):
        item = obj.get("item") or {}
        return _convert_item(kind, item, turn)
    return []


def _convert_item(kind: str, item: Mapping[str, Any], turn: CodexTurn) -> list[events.AgentEvent]:
    item_type = item.get("type")
    done = kind == "item.completed"
    if item_type == "agent_message":
        return [events.TextBlock(str(item.get("text") or ""))] if done else []
    if item_type == "reasoning":
        text = str(item.get("text") or "")
        return [events.ThinkingBlock(text)] if done and text.strip() else []
    if item_type == "error":
        message = str(item.get("message") or "")
        if done and not turn.turn_started:
            return [events.Notice(WARNING_KIND, message)]
        logger.info("codex: %s", _clip(message, _FAILURE_LIMIT))
        return []
    if item_type in ("command_execution", "file_change", "mcp_tool_call"):
        return _tool_events(kind, item, turn)
    if item_type in _IGNORED_ITEMS or kind == "item.updated":
        return []
    name = str(item_type)
    if name in turn._warned_types:
        return []
    turn._warned_types.add(name)
    logger.warning("codex 产生了未处理的事件类型 %s：%s", name, _clip(json.dumps(item), 300))
    return [events.Notice(WARNING_KIND, f"codex 使用了本应用不支持的功能（{name}），已忽略")]


def _tool_events(kind: str, item: Mapping[str, Any], turn: CodexTurn) -> list[events.AgentEvent]:
    call_id = f"{turn.call_prefix}-{item.get('id')}"
    out: list[events.AgentEvent] = []
    if kind in ("item.started", "item.completed") and call_id not in turn._open_calls:
        turn._open_calls.add(call_id)
        out.append(_tool_call(call_id, item, turn.workdir))
    if kind == "item.completed":
        out.append(_tool_result(call_id, item))
    return out


def _tool_call(call_id: str, item: Mapping[str, Any], workdir: Path) -> events.ToolCall:
    item_type = item.get("type")
    if item_type == "command_execution":
        return events.ToolCall(call_id, "shell", {"command": str(item.get("command") or "")})
    if item_type == "file_change":
        changes = [
            {"path": _relative(str(change.get("path") or ""), workdir), "kind": change.get("kind")}
            for change in item.get("changes") or []
        ]
        args: dict[str, object] = {"changes": changes}
        if len(changes) == 1:
            args["path"] = changes[0]["path"]
        return events.ToolCall(call_id, "apply_patch", args)
    arguments = item.get("arguments")
    return events.ToolCall(
        call_id,
        str(item.get("tool") or "?"),
        dict(arguments) if isinstance(arguments, dict) else {},
    )


def _tool_result(call_id: str, item: Mapping[str, Any]) -> events.ToolResult:
    item_type = item.get("type")
    failed = item.get("status") == "failed"
    if item_type == "command_execution":
        output = str(item.get("aggregated_output") or "")
        code = item.get("exit_code")
        is_error = failed or (code is not None and code != 0)
        text = output if not is_error else f"{output}\n（退出码 {code}）".lstrip("\n")
        return events.ToolResult(call_id, text, is_error=is_error)
    if item_type == "file_change":
        paths = ", ".join(str(change.get("path")) for change in item.get("changes") or [])
        return events.ToolResult(
            call_id, ("修改失败：" if failed else "已修改：") + paths, is_error=failed
        )
    error = item.get("error") or {}
    result = item.get("result") or {}
    texts: list[str] = []
    images: list[events.ImageData] = []
    for block in result.get("content") or []:
        if block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
        elif block.get("type") == "image" and block.get("data"):
            images.append(
                events.ImageData(str(block.get("mimeType") or "image/png"), block["data"])
            )
    if error:
        texts.append(str(error.get("message") or error))
    is_error = failed or bool(error) or bool(result.get("is_error") or result.get("isError"))
    return events.ToolResult(call_id, "\n".join(texts), images=images, is_error=is_error)


def _relative(path: str, workdir: Path) -> str:
    try:
        return Path(path).relative_to(workdir).as_posix()
    except ValueError:
        return path


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def failure_message(raw: str) -> str:
    """把 `turn.failed` 的原文整理成给用户看的一句话。"""
    if any(marker in raw for marker in _AUTH_MARKERS):
        return _clip(f"{_AUTH_HINT}（{redact(raw)}）", _FAILURE_LIMIT)
    message = raw
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        inner = parsed.get("error")
        if isinstance(inner, dict) and inner.get("message"):
            message = str(inner["message"])
    return _clip(redact(message), _FAILURE_LIMIT)


_SECRET_PATTERNS = (
    re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"),  # JWT (ChatGPT OAuth tokens)
    re.compile(r"\b(?:sk|rt|ak)-[\w-]{16,}"),  # API / refresh keys
    re.compile(r"[A-Za-z0-9+/_-]{48,}={0,2}"),  # any other long opaque blob
)


def redact(text: str) -> str:
    """去掉看起来像令牌的长串（stderr、错误信息进界面和日志之前）。"""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("***", text)
    return text
