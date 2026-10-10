"""Whether and how agent-written commands and code may run (windows-native design §4.2, ADR 0024).

Every execution point — the Claude CLI's Bash/PowerShell tools, the OpenAI native Shell, and
`render_music` running the agent's synthesis script — asks `exec_mode` with *its own* sandbox
availability, so no caller branches on `sys.platform` by itself:

- `sandboxed`: the point has a sandbox; use it (the switch is ignored).
- `disabled`: no sandbox and the switch is off (the default) — fail closed.
- `unsandboxed`: no sandbox, the switch is on — run without isolation; workspace write checks
  (hooks, `guard`) still apply.

The switch (`STUDIO_ALLOW_UNSANDBOXED_EXEC`, overridable in Settings) is read once at the start
of a turn and carried in `TurnContext`/`ToolContext`; changing it affects the next turn only.
On macOS it has no effect at all.
"""

from __future__ import annotations

import sys
from typing import Literal

from studio.agent.shell_sandbox import sandbox_available as seatbelt_available

ExecMode = Literal["sandboxed", "unsandboxed", "disabled"]

_CLAUDE_SANDBOX_PLATFORMS = ("darwin", "linux")
"""Claude Code sandboxes Bash on macOS, Linux and WSL2 (which reports `linux`); on native
Windows it runs commands unsandboxed (design §4.1)."""


def exec_mode(*, platform: str, sandbox_available: bool, allow_unsandboxed: bool) -> ExecMode:
    """The decision table of design §4.2. macOS never runs unsandboxed: the switch cannot be
    used to turn isolation off there, even if `sandbox-exec` were missing."""
    if sandbox_available:
        return "sandboxed"
    if allow_unsandboxed and platform != "darwin":
        return "unsandboxed"
    return "disabled"


def claude_sandbox_available(platform: str | None = None) -> bool:
    return (platform or sys.platform) in _CLAUDE_SANDBOX_PLATFORMS


def host_exec_mode(allow_unsandboxed: bool, *, platform: str | None = None) -> ExecMode:
    """The mode recorded for a turn (the "命令未隔离" marker): that of the least isolated
    execution point. Seatbelt (OpenAI Shell, `render_music`) exists on fewer platforms than
    Claude's sandbox, so its availability decides."""
    return exec_mode(
        platform=platform or sys.platform,
        sandbox_available=seatbelt_available(),
        allow_unsandboxed=allow_unsandboxed,
    )
