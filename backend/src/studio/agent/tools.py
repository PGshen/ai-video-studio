"""业务工具定义与调用（设计 §4.2）。

`ToolSpec` 是运行时无关的工具描述；`ClaudeRuntime`/`OpenAIRuntime`（T9/T10）
把它转成各自 SDK 的原生工具格式，调用时都经过 `invoke_tool`：参数校验失败
或 handler 抛异常都转成 `is_error=True` 的 `ToolResult`，不会让整轮对话
失败（设计 §4.2 最后一段）。
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine

from studio.agent.events import ImageData


@dataclass(frozen=True, slots=True)
class ToolResult:
    """业务工具 handler 的返回值（没有 `call_id`，那是事件层的概念）。"""

    text: str
    images: list[ImageData] = field(default_factory=list)
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ToolContext:
    """传给工具 handler 的上下文。"""

    project_id: str
    stage: str
    workdir: Path
    record_tool_write: Callable[[str, str], None]
    """`(relpath, sha256) -> None`：handler 写入工具托管文件（例如
    `narrative/timing.json`）之后调用，记录“本轮工具最后一次写入”的内容。
    TurnRunner（T6）用同一个会话累积的记录构造 `scope.guard` 需要的
    `tool_writes` 参数。
    """
    engine: Engine | None = None
    """需要写数据库的工具（例如 `suggest_upstream_change` 写 `suggestions`
    表）用它；大多数工具（文件读写、manim 校验/渲染）不需要，默认 `None`。
    由 `TurnContext.tool_context()` 从 `TurnRunner` 持有的 `Engine` 传入
    （TD-32）。"""


ToolHandler = Callable[[ToolContext, Any], "ToolResult | Awaitable[ToolResult]"]
"""handler 的第二个参数在具体的 `ToolSpec` 上是 `input_model` 的实例（某个
`BaseModel` 子类），但 `ToolSpec` 把不同工具（各自不同的 `input_model`）放
进同一个列表（`list[ToolSpec]`），类型标注只能退到 `Any`——`invoke_tool`
在运行时用 `spec.input_model.model_validate` 校验并构造出真正的参数类型，
handler 实际收到的类型由 `spec.input_model` 保证，不依赖这里的静态标注。
"""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    stages: set[str]
    handler: ToolHandler


async def invoke_tool(spec: ToolSpec, ctx: ToolContext, raw_args: dict[str, Any]) -> ToolResult:
    """校验 `raw_args` 并调用 `spec.handler`。

    参数校验失败（`ValidationError`）或 handler 抛出任意异常，都转成
    `is_error=True` 的 `ToolResult` 返回，而不是向上抛出。
    """
    try:
        args = spec.input_model.model_validate(raw_args)
    except ValidationError as exc:
        return ToolResult(text=f"参数不合法：{exc}", is_error=True)

    try:
        result = spec.handler(ctx, args)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        return ToolResult(text=f"工具执行出错：{exc}", is_error=True)

    return result
