"""`agent.exec_policy`: whether and how agent-written commands and code may run (design §4.2)."""

from __future__ import annotations

import pytest

from studio.agent import exec_policy
from studio.agent.exec_policy import claude_sandbox_available, exec_mode, host_exec_mode


@pytest.mark.parametrize(
    ("platform", "sandbox_available", "allow", "expected"),
    [
        # macOS with sandbox-exec: always sandboxed, the switch cannot turn isolation off.
        ("darwin", True, False, "sandboxed"),
        ("darwin", True, True, "sandboxed"),
        # macOS without a sandbox (should not happen): the switch still has no effect.
        ("darwin", False, False, "disabled"),
        ("darwin", False, True, "disabled"),
        # Windows and other platforms without a sandbox: fail closed unless switched on.
        ("win32", False, False, "disabled"),
        ("win32", False, True, "unsandboxed"),
        ("linux", False, False, "disabled"),
        ("linux", False, True, "unsandboxed"),
        # A platform where this execution point has a sandbox (Claude on Linux).
        ("linux", True, False, "sandboxed"),
        ("linux", True, True, "sandboxed"),
    ],
)
def test_exec_mode_table(
    platform: str, sandbox_available: bool, allow: bool, expected: str
) -> None:
    assert (
        exec_mode(platform=platform, sandbox_available=sandbox_available, allow_unsandboxed=allow)
        == expected
    )


@pytest.mark.parametrize(
    ("platform", "expected"), [("darwin", True), ("linux", True), ("win32", False)]
)
def test_claude_sandbox_platforms(platform: str, expected: bool) -> None:
    """Claude Code's own sandbox: macOS, Linux and WSL2; native Windows runs unsandboxed."""
    assert claude_sandbox_available(platform) is expected


@pytest.mark.parametrize(
    ("seatbelt", "allow", "expected"),
    [(True, True, "sandboxed"), (False, False, "disabled"), (False, True, "unsandboxed")],
)
def test_host_exec_mode_is_the_weakest_point(
    monkeypatch: pytest.MonkeyPatch, seatbelt: bool, allow: bool, expected: str
) -> None:
    """The turn records the mode of the least isolated execution point: Seatbelt (OpenAI Shell,
    render_music) is available on fewer platforms than Claude's sandbox."""
    monkeypatch.setattr(exec_policy, "seatbelt_available", lambda: seatbelt)
    assert host_exec_mode(allow, platform="win32" if not seatbelt else "darwin") == expected
