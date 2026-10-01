"""Agent 运行时事件（设计 §4.1）。

`AgentRuntime.run_turn` 按顺序产出这里定义的事件；`turn_events` 表落库的是
持久化后的子集（合并后的文本块、工具调用、工具结果），token 级的
`TextDelta` 只在内存中经会话总线推给 SSE，不落库（设计 §3.1 说明）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TurnStatus = Literal["done", "failed", "cancelled", "budget_exceeded"]

FILE_TOOL_NAMES = frozenset(
    {
        "write_file",
        "edit_file",
        "shell",
        "apply_patch",
        "Write",
        "Edit",
        "MultiEdit",
        "NotebookEdit",
        "Bash",
    }
)
"""`ToolCall.name` 属于这个集合时视为“文件类工具调用”：TurnRunner（T6）在
这类调用之后需要推送 `workspace_changed` 事件（设计 §4.4 步骤 5）。

- `write_file`/`shell`：FakeRuntime 的原生文件写工具（`fake.write`）和 Shell
  类工具（`fake.shell_write`）。
- OpenAIRuntime（T10）：`apply_patch`/`shell` 是 Responses 路径的原生工具，
  `write_file`/`edit_file` 是 LiteLLM 路径的兜底文件工具。`apply_patch` 的
  `ToolCall.args` 由运行时整理成 `{"type", "path", "diff"}`，兜底工具的参数
  本来就有 `path`，所以这几种都能推送精确路径；`shell` 只有 `commands`，推送
  空列表。
- `Write`/`Edit`/`MultiEdit`/`NotebookEdit`/`Bash`：Claude Code 原生工具名
  （T9：ClaudeRuntime 原样保留原生工具名，不映射成规范名，界面上看到的就是
  SDK 真实调用的工具）。它们的参数里没有 `path`（Claude 用 `file_path`/
  `notebook_path`/`command`），TurnRunner 因此推送空路径列表，表示"路径未知，
  整体刷新"。

其中只有写文件类工具受事前拦截约束，Shell 类只能靠事后 `guard` 兜底。
"""

AuthMode = Literal["api_key", "login"]


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
class ThinkingDelta:
    """token 级思考文本增量，只发布不落库（和 `TextDelta` 一样）。"""

    text: str


@dataclass(frozen=True, slots=True)
class ThinkingBlock:
    """一段完整的思考文本（落库为 `turn_events.type == "thinking"`）。"""

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
    """本轮内新增（不是会话累计）的用量；一轮可以产出多个，TurnRunner 累加。
    （ClaudeRuntime 每轮一个；OpenAIRuntime 每次模型调用一个，成本预算因此能在
    轮中途生效。）

    `auth == "login"`（Claude 本机登录/订阅账号）时 `cost_usd` 只是 CLI 的估算，
    TurnRunner 不按它强制成本预算（计划决策记录 2026-09-27）。
    """

    input_tokens: int
    output_tokens: int
    cost_usd: float
    auth: AuthMode | None = None
    priced: bool = True
    """`False`：模型配置没有单价，`cost_usd` 只是 0 占位、没有统计成本（OpenAIRuntime，
    T10 审查后修复）。TurnRunner 据此每轮发一次 `cost_unpriced` 提示，并把 turn 的
    `cost_usd` 记为空，界面不会显示成 $0。"""
    includes_carryover: bool = False
    """`True`：`cost_usd` 还含同一 SDK 会话上一轮没拿到结果消息（被强制取消或出错）
    的花费。ClaudeRuntime 只能从 SDK 的会话累计值求差，那一轮的花费到本轮才算得出，
    因此计入本轮并标注（TD-11，M1x T3）。这只保证"最终拿到结果消息时不会重复计"，
    不保证"不丢"：会话首轮就被强制取消时没有下一轮可以归属，那笔花费直接丢失，
    是目前唯一已知的例外（TD-25）。"""


@dataclass(frozen=True, slots=True)
class TurnEnd:
    resume_ref: str | None
    status: TurnStatus
    error: str | None = None


AgentEvent = (
    TextDelta | TextBlock | ThinkingDelta | ThinkingBlock | ToolCall | ToolResult | Usage | TurnEnd
)
