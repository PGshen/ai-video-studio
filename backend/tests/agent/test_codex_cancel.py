"""取消与进程清理（codex-runtime T4）。

codex 把模型执行的命令放在独立进程组里；SIGINT 时 codex 自己收掉它们，强杀 codex 则会留下
孤儿（codex.md「续会话、取消与用量」）。假 CLI 用 `FAKE_CODEX_HANG` 模拟这两种情况。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from studio.agent import events
from studio.agent.codex_procs import descendants
from studio.agent.codex_runtime import CodexLedger, CodexRuntime
from studio.agent.runtime import Budget, CancelToken, TurnContext, UserInput
from studio.db.repo.profiles import ModelProfileValue
from studio.workspace.scope import WriteScope

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals and process groups")

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE = ModelProfileValue(
    "p", "codex-login", "openai", "gpt-6.1-sol", "codex", None, None, True, None, None, None, None
)
THREAD = "01a1cafe-0000-7000-8000-000000000001"


def test_descendants_walks_the_process_tree() -> None:
    table = [
        (10, 1, 10),  # codex
        (11, 10, 11),  # a command in its own process group
        (12, 11, 11),  # its child
        (13, 12, 13),  # grandchild with yet another group
        (20, 1, 20),  # unrelated
    ]
    assert sorted(descendants(10, table)) == [(11, 11), (12, 11), (13, 13)]
    assert descendants(20, table) == []


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _ctx(workdir: Path, token: CancelToken) -> TurnContext:
    return TurnContext(
        system_prompt="s",
        user_input=UserInput(text="run sleep"),
        tools=[],
        workdir=workdir,
        model_profile=PROFILE,
        resume_ref=THREAD,
        cancel_token=token,
        budget=Budget(),
        write_scope=WriteScope(writable=["**"], tool_managed=[]),
        project_id=None,
        stage="topic",
        record_tool_write=lambda *_: None,
    )


async def _cancelled_turn(
    tmp_path: Path, fake_codex_bin: Path, hang: str
) -> tuple[list[events.AgentEvent], int, float]:
    script = tmp_path / "start.jsonl"
    script.write_text(
        json.dumps({"type": "thread.started", "thread_id": THREAD})
        + "\n"
        + '{"type":"turn.started"}\n',
        encoding="utf-8",
    )
    pid_file = tmp_path / "child.pid"
    environ = {
        "PATH": os.environ.get("PATH", ""),
        "FAKE_CODEX_SCRIPT": str(script),
        "FAKE_CODEX_HANG": hang,
        "FAKE_CODEX_CHILD_PID": str(pid_file),
    }
    workdir = tmp_path / "ws"
    workdir.mkdir()
    runtime = CodexRuntime(tmp_path / "data", fake_codex_bin, environ=environ, cancel_grace_s=1.0)
    token = CancelToken()
    out: list[events.AgentEvent] = []
    started = 0.0
    async with asyncio.timeout(20):
        async for event in runtime.run_turn(_ctx(workdir, token)):
            out.append(event)
            if isinstance(event, events.ToolCall):
                started = time.monotonic()
                token.cancel()
    return out, int(pid_file.read_text(encoding="utf-8")), time.monotonic() - started


async def test_sigint_lets_codex_clean_up(tmp_path: Path, fake_codex_bin: Path) -> None:
    out, child, elapsed = await _cancelled_turn(tmp_path, fake_codex_bin, "handle")
    assert out[-1] == events.TurnEnd(resume_ref=THREAD, status="cancelled")
    assert elapsed < 1.0  # no need to wait for the grace period
    assert not _alive(child)
    entry = CodexLedger(tmp_path / "data" / "codex" / "ledger").get(THREAD)
    assert entry is not None and entry.unsettled


async def test_force_kill_also_reaps_orphaned_command_groups(
    tmp_path: Path, fake_codex_bin: Path
) -> None:
    out, child, elapsed = await _cancelled_turn(tmp_path, fake_codex_bin, "ignore")
    assert out[-1] == events.TurnEnd(resume_ref=THREAD, status="cancelled")
    assert 1.0 <= elapsed < 10  # waited for the grace period, then forced
    # The `sleep` was in its own process group and still held our stdout pipe.
    for _ in range(50):
        if not _alive(child):
            break
        await asyncio.sleep(0.05)
    assert not _alive(child)
