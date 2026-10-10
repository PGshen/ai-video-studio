"""`LocalShellExecutor` 的测试（TD-16 从 `test_openai_runtime.py` 迁出）。

命令都经 `sandbox-exec` 真实执行，只在 macOS 上跑（计划 M1x T9 写明的 skipif 理由）；
沙箱策略本身的测试在 `test_shell_sandbox.py`。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from agents import RunContextWrapper, ShellCallData, ShellCommandRequest
from agents.tool import ShellActionRequest

from studio.agent import shell as shell_module
from studio.agent.shell import LocalShellExecutor

pytestmark = pytest.mark.macos_only(
    "Shell 经 sandbox-exec 执行，只存在于 macOS（计划 M1x T9）；"
    "无隔离模式见 test_shell_unsandboxed.py"
)


def _request(commands: list[str], timeout_ms: int | None = None) -> ShellCommandRequest:
    data = ShellCallData(
        call_id="s1", action=ShellActionRequest(commands=commands, timeout_ms=timeout_ms)
    )
    return ShellCommandRequest(ctx_wrapper=RunContextWrapper(context=None), data=data)


class TestShellExecutor:
    async def test_uses_injected_environ_without_secrets(
        self, workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STUDIO_ONLY_IN_PROCESS_ENV", "leak")
        environ = {"PATH": os.environ["PATH"], "FOO": "bar", "MY_TOKEN": "secret"}
        executor = LocalShellExecutor(workdir, set(), environ=environ)

        result = await executor(_request(['echo "$FOO|$MY_TOKEN|$STUDIO_ONLY_IN_PROCESS_ENV"']))

        assert result.output[0].stdout.strip() == "bar||"

    async def test_runs_in_workdir_and_captures_output(self, workdir: Path) -> None:
        failed: set[str] = set()
        result = await LocalShellExecutor(workdir, failed)(_request(["pwd", "echo err >&2"]))

        first, second = result.output
        assert first.stdout.strip() == str(workdir.resolve())
        assert first.exit_code == 0
        assert second.stderr.strip() == "err"
        assert failed == set()

    async def test_timeout_kills_command(self, workdir: Path) -> None:
        failed: set[str] = set()
        executor = LocalShellExecutor(workdir, failed)

        result = await asyncio.wait_for(executor(_request(["sleep 5"], timeout_ms=200)), 3)

        (output,) = result.output
        assert output.status == "timeout"
        assert failed == {"s1"}

    async def test_nonzero_exit_marks_failed(self, workdir: Path) -> None:
        failed: set[str] = set()
        result = await LocalShellExecutor(workdir, failed)(_request(["exit 2"]))

        assert result.output[0].exit_code == 2
        assert failed == {"s1"}

    async def test_output_is_truncated(self, workdir: Path) -> None:
        executor = LocalShellExecutor(workdir, set(), max_output_chars=100)
        result = await executor(_request(["yes x | head -c 5000"]))

        assert len(result.output[0].stdout) < 200
        assert "截断" in result.output[0].stdout

    async def test_secrets_are_not_inherited(
        self, workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SOME_API_KEY", "leak")
        monkeypatch.setenv("HARMLESS_VALUE", "ok")
        executor = LocalShellExecutor(workdir, set())

        result = await executor(_request(['echo "[$SOME_API_KEY][$HARMLESS_VALUE]"']))

        assert result.output[0].stdout.strip() == "[][ok]"


async def _group_gone(pgid: int) -> bool:
    if sys.platform == "win32":
        raise AssertionError("process groups are POSIX-only")
    for _ in range(100):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True  # pid reused by a process we do not own
        await asyncio.sleep(0.02)
    return False


class TestShellProcessGroup:
    @pytest.mark.parametrize(
        "background",
        [
            "nohup sh -c 'sleep 0.5; touch marker' > /dev/null 2>&1 &",
            "(sleep 0.5; touch marker) &",  # still holds the stdout pipe
        ],
    )
    async def test_background_processes_die_with_the_command(
        self, workdir: Path, background: str
    ) -> None:
        executor = LocalShellExecutor(workdir, set())

        result = await asyncio.wait_for(executor(_request([f"echo $$; {background}"])), 3)

        pgid = int(result.output[0].stdout.split()[0])
        assert await _group_gone(pgid)
        await asyncio.sleep(0.8)
        assert not (workdir / "marker").exists()

    async def test_output_flood_is_capped_and_killed(self, workdir: Path) -> None:
        failed: set[str] = set()
        executor = LocalShellExecutor(workdir, failed, max_output_chars=1000)

        result = await asyncio.wait_for(executor(_request(["yes"], timeout_ms=10_000)), 5)

        (output,) = result.output
        assert output.status == "completed"
        assert len(output.stdout) < 1200
        assert "终止" in output.stderr
        assert failed == {"s1"}


class TestCancelReaderCleanup:
    """TD-14：取消时（无论落在等待进程退出，还是落在之后的 reader drain 窗口内）都要
    显式取消 reader 任务并等它们真正结束，不留下未完成的 task。"""

    async def test_no_pending_reader_tasks_after_cancel_during_drain(
        self, workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def slow_read_capped(stream: object, cap: int, on_overflow: object) -> bytes:
            # Simulate a reader that is still draining (e.g. a detached child still holding
            # the pipe) when cancellation lands inside the post-exit drain window.
            await asyncio.sleep(1.0)
            return b""

        monkeypatch.setattr(shell_module, "_read_capped", slow_read_capped)
        executor = LocalShellExecutor(workdir, set())

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(executor(_request(["true"])), timeout=0.2)

        pending_readers = [
            task
            for task in asyncio.all_tasks()
            if not task.done()
            and (coro := task.get_coro()) is not None
            and getattr(coro, "__name__", "") == "slow_read_capped"
        ]
        assert pending_readers == []
