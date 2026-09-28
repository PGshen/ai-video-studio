"""运行时无关的核心类型（设计 §4.1）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from studio.agent.events import AgentEvent, ImageData
from studio.agent.tools import ToolSpec
from studio.db.repo.profiles import ModelProfileValue
from studio.workspace.scope import WriteScope


@dataclass(frozen=True, slots=True)
class UserInput:
    """用户一轮消息：文本 + 可选图片（M1 界面只发文本，字段先保留，设计
    "不包含" 一节）。
    """

    text: str
    images: list[ImageData] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Budget:
    """一轮对话的预算上限；任一项为 `None` 表示不限制。"""

    max_steps: int | None = None
    max_cost_usd: float | None = None


class CancelToken:
    """`asyncio.Event` 的薄包装：`cancel()` 置位一次，其余各处只读查询/等待。"""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


@dataclass(frozen=True, slots=True)
class TurnContext:
    """`AgentRuntime.run_turn` 的输入（设计 §4.1）。

    `project_id`/`stage`/`record_tool_write` 是设计 §4.1 原始字段列表之外
    的补充（审查后修复，见计划决策记录）：运行时在处理业务工具调用时需要
    构造 `tools.ToolContext(project_id, stage, workdir, record_tool_write)`
    才能调用 `tools.invoke_tool`，这三项和 `ToolContext` 的字段一一对应，
    直接放进 `TurnContext` 比额外引入一个 `make_tool_context` 工厂函数更
    简单——`TurnRunner`（T6）本来就持有这些值，构造 `TurnContext` 时一并
    传入即可，运行时（`FakeRuntime`/`ClaudeRuntime`/`OpenAIRuntime`）不需要
    再从别处取它们。
    """

    system_prompt: str
    user_input: UserInput
    tools: list[ToolSpec]
    workdir: Path
    model_profile: ModelProfileValue
    resume_ref: str | None
    cancel_token: CancelToken
    budget: Budget
    write_scope: WriteScope
    project_id: str
    stage: str
    record_tool_write: Callable[[str, str], None]
    allow_web: bool = False
    """是否开放联网工具（Claude 的 WebSearch/WebFetch）；TurnRunner 从
    `StageDefinition.allow_web` 取值（T9 控制者裁定：topic 开、其余关）。
    """


@runtime_checkable
class AgentRuntime(Protocol):
    """统一的运行时接口；`ClaudeRuntime`/`OpenAIRuntime`（T9/T10）、
    `FakeRuntime`（本任务）都实现它。
    """

    def run_turn(self, ctx: TurnContext) -> AsyncIterator[AgentEvent]: ...


RuntimeConstructor = Callable[[], AgentRuntime]


class RuntimeFactory:
    """runtime 名 → 构造函数的注册表（控制者裁定 R2）。

    本任务只提供注册表本身和 `fake` 的注册函数（`studio.agent.fake.register_fake`）；
    `claude`/`openai` 由 `main` 在启动时用各自的 `model_profile` 配置构造好
    适配器后调用 `register` 接入（T9/T10）。
    """

    def __init__(self) -> None:
        self._constructors: dict[str, RuntimeConstructor] = {}

    def register(self, name: str, constructor: RuntimeConstructor) -> None:
        self._constructors[name] = constructor

    def has(self, name: str) -> bool:
        """`name` 是否已注册；创建会话前用来判断能否直接给出 400（T8 控制者裁定 1）。"""
        return name in self._constructors

    def create(self, name: str) -> AgentRuntime:
        try:
            constructor = self._constructors[name]
        except KeyError as exc:
            raise KeyError(f"未注册的运行时：{name}") from exc
        return constructor()
