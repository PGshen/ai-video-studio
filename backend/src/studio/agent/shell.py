"""OpenAI Agents SDK `ShellTool` 的本地 executor（TD-16 从 `openai_runtime.py` 拆出）。

每条命令经 macOS `sandbox-exec` 运行（T9，TD-20，配置见 `shell_sandbox`）：只能写
当前工作区和它的 `.cache/tmp`，读不到 `deny_read`（运行时传仓库根与 `data_dir`）中
工作区以外的部分，没有网络。真正 spawn 子进程的调用集中在 `_run`。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import signal
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from agents import ShellCallOutcome, ShellCommandOutput, ShellCommandRequest, ShellResult

from studio.agent.shell_sandbox import SANDBOX_EXEC, sandbox_tmpdir, seatbelt_profile

SHELL_DEFAULT_TIMEOUT_S = 120.0
SHELL_MAX_TIMEOUT_S = 600.0
SHELL_MAX_OUTPUT_CHARS = 20_000
_SECRET_ENV_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)
"""名字匹配的环境变量不传给 Shell 子进程，减少 key 被命令意外打印出来；读文件的
边界由沙箱（`deny_read`）负责。"""


def _shell_env(environ: Mapping[str, str], tmpdir: Path) -> dict[str, str]:
    env = {name: value for name, value in environ.items() if not _SECRET_ENV_RE.search(name)}
    env["TMPDIR"] = str(tmpdir)
    return env


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（输出过长，已截断，共 {len(text)} 字符）"


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


async def _read_capped(
    stream: asyncio.StreamReader | None, cap: int, on_overflow: Callable[[], None]
) -> bytes:
    """读到 EOF，只保留前 `cap` 字节；超过时调用一次 `on_overflow`（杀进程组），
    之后继续读并丢弃，直到管道关闭。"""
    if stream is None:
        return b""
    kept = bytearray()
    overflowed = False
    while chunk := await stream.read(65536):
        room = cap - len(kept)
        if room > 0:
            kept += chunk[:room]
        if len(chunk) > room and not overflowed:
            overflowed = True
            on_overflow()
    return bytes(kept)


async def _wait_for_exit(proc: asyncio.subprocess.Process, timeout: float) -> bool:
    """等 shell 进程本身退出（`True`）或超时（`False`）。

    不能用 `proc.wait()`：asyncio 要等所有管道都关闭才让它返回，而后台子进程
    继承了 stdout，会一直拖到它们自己结束——那样就来不及在它们改工作区之前杀掉。
    `returncode` 在进程退出时就会被设置，这里轮询它。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while proc.returncode is None:
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.02)
    return True


_READER_DRAIN_TIMEOUT_S = 2.0
"""命令结束并杀掉进程组后，等管道读完的上限；逃出进程组（`setsid`）又占着管道的
进程会让读取一直挂起，超时后放弃读取。"""


class LocalShellExecutor:
    """`ShellTool` 的本地 executor：命令在工作区目录下、`sandbox-exec` 沙箱内逐条执行。

    沙箱（`shell_sandbox.seatbelt_profile`）只放行写当前工作区（含 `TMPDIR` =
    `<workdir>/.cache/tmp`），拒读 `deny_read` 但放回当前工作区，禁止网络。工作区内
    越出阶段可写范围的改动仍由轮末 `guard` 还原（设计 §4.3 第 2 道防线）。调用方须
    先确认 `shell_sandbox.sandbox_available()`（运行时经 `native_shell_supported`）。

    每条命令在自己的进程组里运行（`start_new_session`）；命令结束（无论退出码）、
    超时、输出超限或被取消时都杀掉整个进程组，所以 `nohup ... &` 之类的后台进程
    不会活过这次调用——否则它们可能在轮末 `guard` 和快照之后才改工作区，改动会
    进入下一轮的基线、永远不会被还原。用 `setsid` 等方式主动脱离进程组的进程
    管不到。

    超时、输出超限或非零退出码的调用记进 `failed`，运行时据此把对应的
    `ToolResult` 标记为 `is_error`。
    """

    def __init__(
        self,
        workdir: Path,
        failed: set[str],
        *,
        default_timeout_s: float = SHELL_DEFAULT_TIMEOUT_S,
        max_output_chars: int = SHELL_MAX_OUTPUT_CHARS,
        environ: Mapping[str, str] | None = None,
        deny_read: Sequence[Path] = (),
        sandbox_exec: Path = SANDBOX_EXEC,
    ) -> None:
        self._workdir = workdir
        self._tmpdir = sandbox_tmpdir(workdir.resolve())
        self._profile = seatbelt_profile(workdir, deny_read)
        self._sandbox_exec = sandbox_exec
        self._environ = environ if environ is not None else os.environ
        self._failed = failed
        self._default_timeout_s = default_timeout_s
        self._max_output_chars = max_output_chars

    async def __call__(self, request: ShellCommandRequest) -> ShellResult:
        action = request.data.action
        timeout = action.timeout_ms / 1000 if action.timeout_ms else self._default_timeout_s
        timeout = min(timeout, SHELL_MAX_TIMEOUT_S)
        limit = min(action.max_output_length or self._max_output_chars, self._max_output_chars)
        outputs: list[ShellCommandOutput] = []
        for command in action.commands:
            output, failed = await self._run(command, timeout, limit)
            outputs.append(output)
            if failed:
                self._failed.add(request.data.call_id)
            if output.status == "timeout":
                break
        return ShellResult(output=outputs)

    async def _run(
        self, command: str, timeout: float, limit: int
    ) -> tuple[ShellCommandOutput, bool]:
        self._tmpdir.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            str(self._sandbox_exec),
            "-p",
            self._profile,
            "/bin/sh",
            "-c",
            command,
            cwd=self._workdir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_shell_env(self._environ, self._tmpdir),
            start_new_session=True,
        )
        overflowed = False

        def on_overflow() -> None:
            nonlocal overflowed
            overflowed = True
            _kill_group(proc)

        cap = limit * 4  # UTF-8 needs at most 4 bytes per character
        readers = [
            asyncio.create_task(_read_capped(stream, cap, on_overflow))
            for stream in (proc.stdout, proc.stderr)
        ]
        try:
            exited = await _wait_for_exit(proc, timeout)
            timed_out = not exited
            # Always kill the group: background children must not outlive the command.
            _kill_group(proc)
            done, pending = await asyncio.wait(
                [*readers, asyncio.ensure_future(proc.wait())], timeout=_READER_DRAIN_TIMEOUT_S
            )
            for task in pending:
                task.cancel()
            stdout, stderr = (
                reader.result() if reader in done and not reader.cancelled() else b""
                for reader in readers
            )
        except asyncio.CancelledError:
            # TD-14: cancellation can land either while waiting for the process to exit or
            # while draining the readers above; either way, explicitly cancel the readers and
            # wait for them to actually finish instead of leaving them dangling.
            _kill_group(proc)
            for reader in readers:
                reader.cancel()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*readers, return_exceptions=True), _READER_DRAIN_TIMEOUT_S
                )
            raise

        stdout_text = _truncate(stdout.decode("utf-8", errors="replace"), limit)
        stderr_text = _truncate(stderr.decode("utf-8", errors="replace"), limit)
        if timed_out:
            note = f"命令超时（{timeout:g} 秒），已终止"
            return ShellCommandOutput(
                stdout=stdout_text,
                stderr=f"{stderr_text}\n{note}" if stderr_text else note,
                outcome=ShellCallOutcome(type="timeout"),
                command=command,
            ), True
        if overflowed:
            stderr_text += f"\n…（输出超过上限 {limit} 字符，命令已被终止）"
        output = ShellCommandOutput(
            stdout=stdout_text,
            stderr=stderr_text,
            outcome=ShellCallOutcome(type="exit", exit_code=proc.returncode),
            command=command,
        )
        return output, overflowed or proc.returncode != 0
