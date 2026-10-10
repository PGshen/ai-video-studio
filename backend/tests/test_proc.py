"""`studio.proc`: spawning controlled subprocesses and killing whole process trees (design §6).

Both platform branches are tested through the `platform` argument; each platform also has one
real end-to-end case (a child that starts a grandchild, then the whole tree is killed).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from fixtures.processes import pid_alive, wait_gone
from studio import proc

# ---- spawn_kwargs / child_env ----


def test_spawn_kwargs_posix_starts_a_new_session() -> None:
    assert proc.spawn_kwargs("darwin") == {"start_new_session": True}
    assert proc.spawn_kwargs("linux") == {"start_new_session": True}


def test_spawn_kwargs_windows_starts_a_new_process_group() -> None:
    assert proc.spawn_kwargs("win32") == {"creationflags": 0x00000200}


def test_child_env_adds_utf8_mode_without_touching_the_base() -> None:
    base = {"PATH": "/bin"}
    env = proc.child_env(base, platform="darwin", environ={"SYSTEMROOT": "C:\\Windows"})
    assert env == {"PATH": "/bin", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    assert base == {"PATH": "/bin"}


def test_child_env_on_windows_keeps_what_python_needs_to_start() -> None:
    """A whitelisted env without SYSTEMROOT makes Windows Python die at startup."""
    environ = {
        "SYSTEMROOT": "C:\\Windows",
        "WINDIR": "C:\\Windows",
        "COMSPEC": "C:\\Windows\\system32\\cmd.exe",
        "PATHEXT": ".EXE",
        "OPENAI_API_KEY": "sk-secret",
    }
    env = proc.child_env({"PATH": "C:\\bin"}, platform="win32", environ=environ)
    assert env["SYSTEMROOT"] == "C:\\Windows"
    assert env["WINDIR"] == "C:\\Windows"
    assert env["COMSPEC"].endswith("cmd.exe")
    assert env["PATHEXT"] == ".EXE"
    assert "OPENAI_API_KEY" not in env


def test_child_env_does_not_override_explicit_values() -> None:
    env = proc.child_env({"SYSTEMROOT": "D:\\Win"}, platform="win32", environ={"SYSTEMROOT": "C:"})
    assert env["SYSTEMROOT"] == "D:\\Win"


# ---- kill_tree: Windows branch through a fake taskkill ----


class _FakeProcess:
    def __init__(self, pid: int = 4242, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def _record_taskkill(monkeypatch: pytest.MonkeyPatch, returncode: int) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        return subprocess.CompletedProcess(argv, returncode)

    monkeypatch.setattr(proc.subprocess, "run", fake_run)
    return calls


async def test_windows_kill_tree_runs_taskkill_on_the_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_taskkill(monkeypatch, 0)
    fake = _FakeProcess()
    await proc.kill_tree(fake, platform="win32")
    assert calls == [["taskkill", "/T", "/F", "/PID", "4242"]]
    assert not fake.killed


async def test_windows_kill_tree_falls_back_to_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_taskkill(monkeypatch, 128)
    fake = _FakeProcess()
    await proc.kill_tree(fake, platform="win32")
    assert fake.killed


async def test_windows_kill_tree_skips_an_exited_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Its PID may already belong to someone else; `/T` would kill that process's tree."""
    calls = _record_taskkill(monkeypatch, 0)
    await proc.kill_tree(_FakeProcess(returncode=0), platform="win32")
    assert calls == []


def test_kill_proc_tree_is_the_sync_form(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_taskkill(monkeypatch, 0)
    proc.kill_proc_tree(_FakeProcess(), platform="win32")
    assert calls == [["taskkill", "/T", "/F", "/PID", "4242"]]


def test_kill_tree_sync_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_taskkill(monkeypatch, 128)
    assert proc.kill_tree_sync(4242, platform="win32") is False


def test_kill_tree_sync_without_taskkill_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(proc.subprocess, "run", missing)
    assert proc.kill_tree_sync(4242, platform="win32") is False


# ---- real process trees ----

_PARENT = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(sys.argv[1], "w", encoding="utf-8").write(str(child.pid))
time.sleep(60)
"""


async def test_kill_tree_kills_the_grandchild_too(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    parent = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _PARENT,
        str(pid_file),
        stdin=asyncio.subprocess.DEVNULL,
        env=proc.child_env(dict(os.environ)),
        **proc.spawn_kwargs(),
    )
    deadline = time.monotonic() + 20
    while not (pid_file.exists() and pid_file.read_text(encoding="utf-8")):
        assert time.monotonic() < deadline, "the parent never started its child"
        await asyncio.sleep(0.05)
    grandchild = int(pid_file.read_text(encoding="utf-8"))
    assert pid_alive(grandchild)

    await proc.kill_tree(parent)
    await asyncio.wait_for(parent.wait(), 10)

    assert await wait_gone(grandchild), f"grandchild {grandchild} survived kill_tree"


def test_run_killing_tree_returns_output_like_subprocess_run() -> None:
    done = proc.run_killing_tree(
        [sys.executable, "-c", "import sys; sys.stdout.write('中文'); sys.exit(3)"], timeout=30
    )
    assert done.returncode == 3
    assert done.stdout.decode("utf-8") == "中文"  # child runs in UTF-8 mode (child_env)


async def test_run_killing_tree_kills_the_tree_on_timeout(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    with pytest.raises(subprocess.TimeoutExpired):
        await asyncio.to_thread(
            proc.run_killing_tree,
            [sys.executable, "-c", _PARENT, str(pid_file)],
            timeout=3,
        )
    grandchild = int(pid_file.read_text(encoding="utf-8"))
    assert await wait_gone(grandchild), f"grandchild {grandchild} survived the timeout"
