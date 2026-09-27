"""Agent 运行时事件（设计 §4.1）。

`AgentRuntime.run_turn` 按顺序产出这里定义的事件；`turn_events` 表落库的是
持久化后的子集（合并后的文本块、工具调用、工具结果），token 级的
`TextDelta` 只在内存中经会话总线推给 SSE，不落库（设计 §3.1 说明）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TurnStatus = Literal["done", "failed", "cancelled", "budget_exceeded"]

FILE_TOOL_NAMES = frozenset({"write_file", "shell"})
"""`ToolCall.name` 属于这个集合时视为“文件类工具调用”：TurnRunner（T6）在
这类调用之后需要推送 `workspace_changed` 事件（设计 §4.4 步骤 5）。
`write_file` 对应原生文件写工具（`fake.write`），`shell` 对应 Shell 类原生
工具（`fake.shell_write`）——两者都可能改动工作区文件，但只有前者受事前
拦截约束。
"""


@dataclass(frozen=True, slots=True)
class ImageData:
    """一张图片：base64 编码内容和 MIME 类型。"""

    media_type: str
    data_base64: str


@dataclass(frozen=True, slots=True)
class TextDelta:
    """token 级文本增量，只发布不落库。"""

    text: str


@dataclass(frozen=True, slots=True)
class TextBlock:
    """一段完整文本（落库为 `turn_events.type == "text"`）。"""

    text: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    args: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """事件层的工具结果，带 `call_id` 以便和对应的 `ToolCall` 配对。

    与 `studio.agent.tools.ToolResult`（业务工具 handler 的返回值，没有
    `call_id`）是两个不同的类型：运行时把 handler 的返回值包上 `call_id`
    后才产出这个事件。
    """

    call_id: str
    text: str
    images: list[ImageData] = field(default_factory=list)
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(frozen=True, slots=True)
class TurnEnd:
    resume_ref: str | None
    status: TurnStatus
    error: str | None = None


AgentEvent = TextDelta | TextBlock | ToolCall | ToolResult | Usage | TurnEnd
