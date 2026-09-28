"""测试用的可编排运行时（设计 §4.1 表格）。

脚本是一串步骤（`say`/`write`/`shell_write`/`call_tool`/`fail`/`sleep`/
`use_cost` 构造出来的 dataclass），`FakeRuntime.run_turn` 按顺序执行，逐步
产出事件：

- `write(path, content)` 模拟一个**原生文件写工具**：先做事前拦截——目标
  路径不在 `ctx.write_scope` 内时，只产出 `ToolCall` + 错误 `ToolResult`，
  不写文件；在范围内则通过 `studio.workspace.files.write_text` 写入（分层
  规则 6：`workspace` 是唯一读写工作区文件的模块），再产出成功的
  `ToolResult`。
- `shell_write(path, content)` 模拟 **Shell 类原生工具**：不做任何事前拦截
  （设计 §4.3：Shell 的越界写入只能靠回合结束时的事后 `guard` 兜底），
  直接调用 `studio.workspace.files.write_text_unscoped`（T5 决策：见计划
  「决策记录」）。
- `call_tool(name, args)` 从 `ctx.tools` 里按名字找到 `ToolSpec` 并经
  `tools.invoke_tool` 调用；找不到时产出错误 `ToolResult`。

`ToolCall.name` 分别是 `"write_file"`、`"shell"`，都属于
`events.FILE_TOOL_NAMES`，T6 的 TurnRunner 据此判断是否需要推送
`workspace_changed`。

`register_fake(factory)` 把 `fake` 注册进 `RuntimeFactory`（控制者裁定
R2）：`FakeRuntime()` 不传脚本时，`run_turn` 用当轮的 `ctx.write_scope` +
`ctx.user_input.text` 现场生成 `default_fake_script`。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from studio.agent import events
from studio.agent.runtime import RuntimeFactory, TurnContext
from studio.agent.tools import invoke_tool
from studio.workspace import files
from studio.workspace.scope import WriteScope, is_writable


@dataclass(frozen=True, slots=True)
class Say:
    text: str


@dataclass(frozen=True, slots=True)
class Write:
    path: str
    content: str


@dataclass(frozen=True, slots=True)
class ShellWrite:
    path: str
    content: str = ""


@dataclass(frozen=True, slots=True)
class CallTool:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Fail:
    message: str


@dataclass(frozen=True, slots=True)
class Sleep:
    seconds: float


@dataclass(frozen=True, slots=True)
class UseCost:
    usd: float


FakeStep = Say | Write | ShellWrite | CallTool | Fail | Sleep | UseCost


def say(text: str) -> Say:
    return Say(text)


def write(path: str, content: str) -> Write:
    return Write(path, content)


def shell_write(path: str, content: str = "") -> ShellWrite:
    return ShellWrite(path, content)


def call_tool(name: str, args: dict[str, Any] | None = None) -> CallTool:
    return CallTool(name, args or {})


def fail(message: str) -> Fail:
    return Fail(message)


def sleep(seconds: float) -> Sleep:
    return Sleep(seconds)


def use_cost(usd: float) -> UseCost:
    return UseCost(usd)


class FakeRuntime:
    """按脚本产出事件的测试运行时。

    `script` 为 `None`（包括零参数构造 `FakeRuntime()`，供
    `register_fake` 注册进 `RuntimeFactory` 使用，见控制者裁定）时，
    `run_turn` 在拿到 `ctx` 之后才用 `default_fake_script(ctx.write_scope,
    ctx.user_input.text)` 现场生成脚本——这样 `FakeRuntime` 能满足
    `RuntimeFactory` 的零参数 `RuntimeConstructor` 签名，同时仍然对每一轮
    的实际 `write_scope`/用户消息作出正确的回显（而不是构造时就固定死）。

    `call_tool` 步骤需要的工具上下文取自 `ctx.tool_context()`（TD-17）。
    步数预算不在这里计数：TurnRunner 统计工具调用、超限时置位取消令牌，
    这里在每一步开始前检查令牌（TD-18）。
    """

    def __init__(self, script: list[FakeStep] | None = None, *, delay_seconds: float = 0) -> None:
        self._script = script
        self._delay_seconds = delay_seconds

    async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
        script = self._script
        if script is None:
            script = default_fake_script(
                ctx.write_scope, ctx.user_input.text, delay_seconds=self._delay_seconds
            )

        call_counter = 0
        total_cost = 0.0

        for step in script:
            if ctx.cancel_token.is_cancelled:
                yield events.TurnEnd(resume_ref=ctx.resume_ref, status="cancelled")
                return

            if isinstance(step, Say):
                yield events.TextBlock(text=step.text)

            elif isinstance(step, Write):
                call_counter += 1
                call_id = f"call-{call_counter}"
                yield events.ToolCall(
                    call_id=call_id,
                    name="write_file",
                    args={"path": step.path, "content": step.content},
                )
                if not is_writable(ctx.write_scope, step.path):
                    yield events.ToolResult(
                        call_id=call_id,
                        text=f"不在可写范围内：{step.path}",
                        is_error=True,
                    )
                    continue
                files.write_text(ctx.workdir, step.path, step.content, ctx.write_scope)
                yield events.ToolResult(call_id=call_id, text=f"已写入 {step.path}")

            elif isinstance(step, ShellWrite):
                call_counter += 1
                call_id = f"call-{call_counter}"
                yield events.ToolCall(
                    call_id=call_id, name="shell", args={"command": f"write {step.path}"}
                )
                files.write_text_unscoped(ctx.workdir, step.path, step.content)
                yield events.ToolResult(call_id=call_id, text=f"已写入 {step.path}")

            elif isinstance(step, CallTool):
                call_counter += 1
                call_id = f"call-{call_counter}"
                yield events.ToolCall(call_id=call_id, name=step.name, args=step.args)
                spec = next((t for t in ctx.tools if t.name == step.name), None)
                if spec is None:
                    yield events.ToolResult(
                        call_id=call_id, text=f"未知工具：{step.name}", is_error=True
                    )
                    continue
                result = await invoke_tool(spec, ctx.tool_context(), step.args)
                yield events.ToolResult(
                    call_id=call_id,
                    text=result.text,
                    images=result.images,
                    is_error=result.is_error,
                )

            elif isinstance(step, Fail):
                yield events.TurnEnd(resume_ref=ctx.resume_ref, status="failed", error=step.message)
                return

            elif isinstance(step, Sleep):
                try:
                    await asyncio.wait_for(ctx.cancel_token.wait(), timeout=step.seconds)
                except TimeoutError:
                    continue
                yield events.TurnEnd(resume_ref=ctx.resume_ref, status="cancelled")
                return

            elif isinstance(step, UseCost):
                total_cost += step.usd
                yield events.Usage(input_tokens=0, output_tokens=0, cost_usd=step.usd)
                if ctx.budget.max_cost_usd is not None and total_cost > ctx.budget.max_cost_usd:
                    yield events.TurnEnd(resume_ref=ctx.resume_ref, status="budget_exceeded")
                    return

            else:  # pragma: no cover -- 穷举 FakeStep 后不可达，防御未来新增步骤忘记处理
                raise TypeError(f"未知的 Fake 脚本步骤：{step!r}")

        yield events.TurnEnd(resume_ref=ctx.resume_ref, status="done")


def _first_writable_dir(write_scope: WriteScope) -> str:
    """从 `write_scope.writable` 的第一条 glob 推出一个目录，供默认脚本把
    `fake-note.md` 写在阶段的产物目录里（AC4 演示）。
    """
    if not write_scope.writable:
        raise ValueError("write_scope 没有声明任何可写路径")

    pattern = write_scope.writable[0]
    for suffix in ("/**", "/*"):
        if pattern.endswith(suffix):
            return pattern[: -len(suffix)]
    return str(PurePosixPath(pattern).parent)


def default_fake_script(
    write_scope: WriteScope, user_text: str, *, delay_seconds: float = 0
) -> list[FakeStep]:
    """`enable_fake_runtime` 时的默认脚本：回显用户消息，并在阶段的第一个
    可写目录里写一个 `fake-note.md`（AC4：端到端演示 agent 改工作区文件）。

    `delay_seconds > 0`（`STUDIO_FAKE_DELAY_SECONDS`）时在回显和写文件之间
    睡这么久（可被取消），用来在浏览器里观察"运行中"状态、做重启中断验证（M6）。
    """
    target_dir = _first_writable_dir(write_scope)
    steps: list[FakeStep] = [say(f"收到：{user_text}")]
    if delay_seconds > 0:
        steps.append(sleep(delay_seconds))
    steps.append(write(f"{target_dir}/fake-note.md", f"echo: {user_text}\n"))
    return steps


def register_fake(factory: RuntimeFactory, *, delay_seconds: float = 0) -> None:
    """把 `fake` 运行时注册进 `factory`（控制者裁定：满足 R2——
    `RuntimeFactory` 只是注册表，T5 不预置任何注册，由各运行时各自的模块
    导出注册函数）。

    `main`（T7 之后）在 `settings.enable_fake_runtime` 为真时调用它。注册的
    构造函数是零参数的 `FakeRuntime()`（`script=None`），每一轮都会在
    `run_turn` 里用当轮的 `ctx` 现场生成默认脚本。
    """
    factory.register("fake", lambda: FakeRuntime(delay_seconds=delay_seconds))
