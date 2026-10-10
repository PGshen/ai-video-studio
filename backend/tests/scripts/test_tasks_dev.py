"""`scripts/tasks.py dev`: pid file, "is this our process", port owners, and the supervisor.

The supervisor test starts real processes (each with a grandchild) and checks that stopping
leaves nothing behind — on whichever platform the suite runs (review points 2 and 6).
"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import time
from pathlib import Path

import pytest

from fixtures.processes import pid_alive

REPO_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("tasks_dev", REPO_ROOT / "scripts" / "tasks.py")
assert _spec is not None and _spec.loader is not None
tasks = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = tasks  # dataclasses look the module up by name
_spec.loader.exec_module(tasks)


# ---- pid file ----


def test_pid_file_round_trip(tmp_path: Path) -> None:
    path = tmp_path / ".dev" / "pids.json"
    entries = [{"name": "api", "pid": 12, "cmd": "uv run uvicorn"}]
    tasks.write_pid_file(path, entries)
    assert tasks.read_pid_file(path) == entries


@pytest.mark.parametrize("content", [None, "", "not json", '{"a": 1}', '[{"name": "x"}]'])
def test_unreadable_pid_file_is_empty(tmp_path: Path, content: str | None) -> None:
    path = tmp_path / "pids.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert tasks.read_pid_file(path) == []


# ---- is this process ours? (review point 2) ----

ROOT = "C:\\dev\\ai-video-studio"
POSIX_ROOT = "/Users/me/ai-video-studio"


@pytest.mark.parametrize(
    ("info", "platform", "expected"),
    [
        (("python.exe", f"python.exe -m uvicorn --reload-dir {ROOT}\\backend\\src"), "win32", True),
        (
            ("uv.exe", f'uv.exe run --project "{ROOT}\\backend" python -m studio.worker'),
            "win32",
            True,
        ),
        (
            ("node.exe", f"node.exe {ROOT.lower()}\\frontend\\node_modules\\vite\\bin\\vite.js"),
            "win32",
            True,
        ),
        (
            ("cmd.exe", f'cmd.exe /c "{ROOT}\\frontend\\node_modules\\.bin\\pnpm.CMD" run dev'),
            "win32",
            True,
        ),
        # PID reused by an unrelated process: right image, wrong command line.
        (("python.exe", "python.exe C:\\other\\app.py"), "win32", False),
        # PID reused by something that mentions the repo but is not one of ours.
        (("explorer.exe", f"explorer.exe {ROOT}"), "win32", False),
        (None, "win32", False),
        (
            ("python3", f"/usr/bin/python3 -m uvicorn --reload-dir {POSIX_ROOT}/backend/src"),
            "darwin",
            True,
        ),
        (("bash", "/bin/bash"), "darwin", False),
    ],
)
def test_belongs_to_project(info: tuple[str, str] | None, platform: str, expected: bool) -> None:
    root = ROOT if platform == "win32" else POSIX_ROOT
    assert tasks.belongs_to_project(info, Path(root), platform=platform) is expected


def test_cleanup_kills_only_our_processes() -> None:
    entries = [
        {"name": "api", "pid": 1, "cmd": "a"},
        {"name": "worker", "pid": 2, "cmd": "b"},
        {"name": "web", "pid": 3, "cmd": "c"},
    ]
    infos = {
        1: ("python.exe", f"python.exe --reload-dir {ROOT}\\backend\\src"),
        2: ("python.exe", "python.exe C:\\elsewhere\\x.py"),  # reused PID: must survive
        3: None,  # already gone
    }
    killed: list[int] = []
    log = io.StringIO()
    tasks.cleanup_stale(
        entries,
        Path(ROOT),
        process_info=infos.get,
        kill=killed.append,
        log=log,
        platform="win32",
    )
    assert killed == [1]
    assert "2" in log.getvalue() and "跳过" in log.getvalue()


# ---- who holds a port ----

NETSTAT = """
活动连接

  协议  本地地址          外部地址        状态           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1180
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       4704
  TCP    127.0.0.1:8000         127.0.0.1:55177        ESTABLISHED     4704
  TCP    127.0.0.1:18000        0.0.0.0:0              LISTENING       999
  TCP    [::1]:5173             [::]:0                 LISTENING       8664
  UDP    0.0.0.0:5353           *:*                                    2000
"""


def test_netstat_listeners() -> None:
    assert tasks.parse_netstat_listeners(NETSTAT, 8000) == [4704]
    assert tasks.parse_netstat_listeners(NETSTAT, 5173) == [8664]
    assert tasks.parse_netstat_listeners(NETSTAT, 9999) == []


# ---- api command (P13) ----


def test_api_reloads_on_posix_only(tmp_path: Path) -> None:
    posix = tasks.api_argv("uv", tmp_path, "127.0.0.1", "8000", platform="darwin")
    assert posix[posix.index("--reload-dir") + 1] == str(tmp_path / "src")
    assert "--reload" in posix and posix[-4:] == ["--host", "127.0.0.1", "--port", "8000"]
    # Windows: `--reload` makes uvicorn pick a SelectorEventLoop (no subprocesses) and its
    # CTRL_C_EVENT restart never reaches a server in our own process group (windows-native T11).
    windows = tasks.api_argv("uv", tmp_path, "127.0.0.1", "8000", platform="win32")
    assert not any(arg.startswith("--reload") for arg in windows)
    assert windows[:5] == ["uv", "run", "--project", str(tmp_path), "uvicorn"]


def test_the_api_event_loop_can_start_subprocesses(tmp_path: Path) -> None:
    """The loop uvicorn builds for our api command must support `create_subprocess_exec`:
    the Claude CLI, Chromium, ffmpeg and the score script all start from the api process."""
    import asyncio

    from uvicorn.loops.asyncio import asyncio_loop_factory

    argv = tasks.api_argv("uv", tmp_path, "127.0.0.1", "8000", platform=sys.platform)
    factory = asyncio_loop_factory(use_subprocess="--reload" in argv)

    async def child_output() -> bytes:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "print('ok')", stdout=asyncio.subprocess.PIPE
        )
        out, _ = await proc.communicate()
        return out

    with asyncio.Runner(loop_factory=factory) as runner:
        assert runner.run(child_output()).strip() == b"ok"


def test_descendant_pids_walks_the_whole_tree() -> None:
    table = [(10, 1), (11, 10), (12, 11), (13, 11), (20, 1), (21, 20), (30, 99)]
    assert sorted(tasks.descendant_pids([10, 20], table)) == [11, 12, 13, 21]
    assert tasks.descendant_pids([99], [(99, 99)]) == []  # self-parented entries do not loop


# ---- supervisor: real processes ----

_SERVICE = """
import subprocess, sys, time
own_session = sys.argv[2] == "1"  # like ffmpeg under `studio.proc.spawn_kwargs()`
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=own_session
)
open(sys.argv[1], "w", encoding="utf-8").write(str(child.pid))
print("ready 中文", flush=True)
time.sleep(120)
"""


def _wait_for(path: Path, timeout: float = 20) -> int:
    deadline = time.monotonic() + timeout
    while not (path.exists() and path.read_text(encoding="utf-8")):
        assert time.monotonic() < deadline, f"{path.name} never appeared"
        time.sleep(0.05)
    return int(path.read_text(encoding="utf-8"))


def _gone(pid: int, timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


@pytest.mark.parametrize("own_session", [False, True], ids=["same-group", "own-session"])
def test_stop_kills_every_tree_and_removes_the_pid_file(tmp_path: Path, own_session: bool) -> None:
    """Review point 6 (process side): nothing survives the supervisor, including grandchildren
    the services put in their own session (worker's ffmpeg is spawned that way)."""
    pid_file = tmp_path / ".dev" / "pids.json"
    services = [
        tasks.Service(
            name,
            [sys.executable, "-c", _SERVICE, str(tmp_path / f"{name}.pid"), str(int(own_session))],
            tmp_path,
        )
        for name in ("api", "worker", "web")
    ]
    out = io.StringIO()
    sup = tasks.Supervisor(
        services, env=tasks.utf8_env(dict(os.environ)), pid_file=pid_file, out=out
    )
    sup.start()
    try:
        grandchildren = [_wait_for(tmp_path / f"{s.name}.pid") for s in services]
        assert [e["name"] for e in tasks.read_pid_file(pid_file)] == ["api", "worker", "web"]
        deadline = time.monotonic() + 10
        while out.getvalue().count("ready 中文") < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
        for name in ("api", "worker", "web"):
            assert f"[{name}] ready 中文" in out.getvalue()
    finally:
        sup.stop()
    for pid in grandchildren:
        assert _gone(pid), f"grandchild {pid} survived"
    for entry in sup.started:
        assert _gone(entry["pid"])
    assert not pid_file.exists()


def test_an_exiting_service_is_reported(tmp_path: Path) -> None:
    services = [
        tasks.Service("api", [sys.executable, "-c", "import time; time.sleep(60)"], tmp_path),
        tasks.Service("worker", [sys.executable, "-c", "raise SystemExit(3)"], tmp_path),
    ]
    sup = tasks.Supervisor(services, env=None, pid_file=tmp_path / "pids.json", out=io.StringIO())
    sup.start()
    try:
        assert sup.wait(poll=0.05) == ("worker", 3)
    finally:
        sup.stop()


def test_output_the_console_cannot_encode_does_not_stop_the_pump(tmp_path: Path) -> None:
    """Vite prints `➜`; on a GBK console that used to kill the output thread (and later stall
    the child on a full pipe)."""
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="gbk", errors="strict", write_through=True)
    code = "print('➜ Local'); print('after 中文', flush=True)"
    sup = tasks.Supervisor(
        [tasks.Service("web", [sys.executable, "-c", code], tmp_path)],
        env=None,
        pid_file=tmp_path / "pids.json",
        out=out,
    )
    sup.start()
    try:
        assert sup.wait(poll=0.05) == ("web", 0)
        deadline = time.monotonic() + 5
        while b"after" not in raw.getvalue() and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        sup.stop()
    text = raw.getvalue().decode("gbk")
    assert "[web] after 中文" in text
    assert "Local" in text
