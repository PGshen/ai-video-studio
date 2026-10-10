"""`LocalShellExecutor` without `sandbox-exec` (ADR 0024 `unsandboxed` mode).

These run for real on every platform: `/bin/sh` on POSIX, Git Bash on Windows. Write checks
(the `guard` restore) do not live in the executor and are covered by the runner tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from agents import RunContextWrapper, ShellCallData, ShellCommandRequest
from agents.tool import ShellActionRequest

from studio.agent import shell as shell_module
from studio.agent.shell import LocalShellExecutor, ShellUnavailable, unsandboxed_shell_argv


def _request(commands: list[str], timeout_ms: int | None = None) -> ShellCommandRequest:
    data = ShellCallData(
        call_id="s1", action=ShellActionRequest(commands=commands, timeout_ms=timeout_ms)
    )
    return ShellCommandRequest(ctx_wrapper=RunContextWrapper(context=None), data=data)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


async def test_runs_in_the_workspace_and_prints_chinese(workdir: Path) -> None:
    """Review point 4: no mojibake on a system whose code page is not UTF-8."""
    executor = LocalShellExecutor(workdir, set(), sandboxed=False)
    result = await executor(_request(["echo 中文 && echo hi > note.txt"]))

    assert result.output[0].stdout.strip() == "中文"
    assert (workdir / "note.txt").read_text(encoding="utf-8").strip() == "hi"


async def test_secrets_are_still_filtered(workdir: Path) -> None:
    environ = {**os.environ, "FOO": "bar", "MY_TOKEN": "secret"}
    executor = LocalShellExecutor(workdir, set(), environ=environ, sandboxed=False)
    result = await executor(_request(['echo "$FOO|$MY_TOKEN"']))
    assert result.output[0].stdout.strip() == "bar|"


async def test_timeout_is_reported_as_failed(workdir: Path) -> None:
    failed: set[str] = set()
    executor = LocalShellExecutor(workdir, failed, sandboxed=False)
    result = await executor(_request(["sleep 30"], timeout_ms=500))
    assert result.output[0].outcome.type == "timeout"
    assert failed == {"s1"}


def test_posix_uses_bin_sh() -> None:
    assert unsandboxed_shell_argv("ls", platform="darwin") == ["/bin/sh", "-c", "ls"]


def test_windows_uses_git_bash_next_to_git(tmp_path: Path) -> None:
    git = tmp_path / "Git" / "cmd" / "git.exe"
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    for path in (git, bash):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    argv = unsandboxed_shell_argv(
        "ls", platform="win32", environ={}, which=lambda name: str(git) if name == "git" else None
    )
    assert argv == [str(bash), "-c", "ls"]


def test_windows_honours_the_claude_code_git_bash_variable(tmp_path: Path) -> None:
    bash = tmp_path / "bash.exe"
    bash.write_bytes(b"")
    environ = {"CLAUDE_CODE_GIT_BASH_PATH": str(bash)}
    argv = unsandboxed_shell_argv("ls", platform="win32", environ=environ, which=lambda _n: None)
    assert argv == [str(bash), "-c", "ls"]


def test_windows_never_falls_back_to_wsl_bash() -> None:
    """`C:\\Windows\\System32\\bash.exe` is WSL: a different file system, not the workspace."""
    with pytest.raises(ShellUnavailable, match="Git"):
        unsandboxed_shell_argv(
            "ls",
            platform="win32",
            environ={},
            which=lambda name: "C:\\Windows\\System32\\bash.exe" if name == "bash" else None,
        )


async def test_missing_git_bash_is_a_failed_call(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(command: str, **_kwargs: object) -> list[str]:
        raise ShellUnavailable("找不到 Git Bash")

    monkeypatch.setattr(shell_module, "unsandboxed_shell_argv", unavailable)
    failed: set[str] = set()
    executor = LocalShellExecutor(workdir, failed, sandboxed=False)
    result = await executor(_request(["echo hi"]))
    assert "Git Bash" in result.output[0].stderr
    assert failed == {"s1"}
