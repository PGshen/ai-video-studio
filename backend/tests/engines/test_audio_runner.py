"""`engines.audio.runner.run_compose`：在临时目录里运行合成脚本并回收产物（设计 §7.3）。

这里用恒等的 `wrap_command`，不依赖沙箱；真实 Seatbelt 的用例标 slow。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from studio.engines.audio.runner import ComposeError, run_compose


def identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


GOOD = """
    import json, os, wave
    tl = json.load(open(os.environ["STUDIO_TIMELINE"]))
    w = wave.open(os.environ["STUDIO_OUT_WAV"], "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
    w.writeframes(b"\\0\\0" * 441)
    w.close()
    doc = {"bpm": 120, "duration": tl["duration"], "events": []}
    json.dump(doc, open(os.environ["STUDIO_OUT_EVENTS"], "w"))
    print("hello from compose")
"""


def _script(tmp_path: Path, body: str) -> tuple[Path, Path, Path]:
    script = tmp_path / "compose.py"
    script.write_text(textwrap.dedent(body))
    timeline = tmp_path / "timeline.json"
    timeline.write_text(json.dumps({"duration": 1.5}))
    out_dir = tmp_path / "run"
    return script, timeline, out_dir


async def test_success_writes_both_products_into_the_out_dir(tmp_path: Path) -> None:
    script, timeline, out_dir = _script(tmp_path, GOOD)
    result = await run_compose(script, timeline, out_dir, timeout=30, wrap_command=identity)
    assert result.wav_path == out_dir / "music.wav" and result.wav_path.is_file()
    assert json.loads(result.events_path.read_text())["duration"] == 1.5
    assert "hello from compose" in result.stdout
    assert result.elapsed >= 0


async def test_the_script_runs_with_the_out_dir_as_cwd_and_a_private_tmpdir(tmp_path: Path) -> None:
    body = (
        GOOD
        + """
    import pathlib
    pathlib.Path("cwd.txt").write_text(os.getcwd())
    pathlib.Path("tmp.txt").write_text(os.environ.get("TMPDIR", ""))
    """
    )
    script, timeline, out_dir = _script(tmp_path, body)
    await run_compose(script, timeline, out_dir, timeout=30, wrap_command=identity)
    assert Path((out_dir / "cwd.txt").read_text()).resolve() == out_dir.resolve()
    assert Path((out_dir / "tmp.txt").read_text()).resolve().is_relative_to(out_dir.resolve())


async def test_the_wrapper_sees_the_command_and_environment(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def spy(argv: list[str], env: dict[str, str]) -> list[str]:
        seen["argv"], seen["env"] = list(argv), dict(env)
        return argv

    script, timeline, out_dir = _script(tmp_path, GOOD)
    await run_compose(script, timeline, out_dir, timeout=30, wrap_command=spy)
    assert seen["argv"] == [sys.executable, str(script)]
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["STUDIO_TIMELINE"] == str(timeline)
    assert env["STUDIO_OUT_WAV"] == str(out_dir / "music.wav")
    assert env["STUDIO_OUT_EVENTS"] == str(out_dir / "events.json")


async def test_secrets_in_the_parent_environment_do_not_reach_the_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    body = (
        GOOD
        + """
    open("leak.txt", "w").write(os.environ.get("ANTHROPIC_API_KEY", "absent"))
    """
    )
    script, timeline, out_dir = _script(tmp_path, body)
    await run_compose(script, timeline, out_dir, timeout=30, wrap_command=identity)
    assert (out_dir / "leak.txt").read_text() == "absent"


async def test_exception_reports_the_stderr_tail(tmp_path: Path) -> None:
    script, timeline, out_dir = _script(tmp_path, "raise RuntimeError('boom in compose')\n")
    with pytest.raises(ComposeError) as info:
        await run_compose(script, timeline, out_dir, timeout=30, wrap_command=identity)
    assert "boom in compose" in str(info.value) and "退出码" in str(info.value)


async def test_missing_products_are_named(tmp_path: Path) -> None:
    only_wav = GOOD.replace('json.dump(doc, open(os.environ["STUDIO_OUT_EVENTS"], "w"))', "pass")
    script, timeline, out_dir = _script(tmp_path, only_wav)
    with pytest.raises(ComposeError) as info:
        await run_compose(script, timeline, out_dir, timeout=30, wrap_command=identity)
    assert "STUDIO_OUT_EVENTS" in str(info.value)
    (tmp_path / "b").mkdir()
    script2, timeline2, out_dir2 = _script(tmp_path / "b", "print('did nothing')\n")
    with pytest.raises(ComposeError) as info2:
        await run_compose(script2, timeline2, out_dir2, timeout=30, wrap_command=identity)
    assert "STUDIO_OUT_WAV" in str(info2.value)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def test_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    body = """
    import os, subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open("child.pid", "w").write(str(child.pid))
    time.sleep(60)
    """
    script, timeline, out_dir = _script(tmp_path, body)
    with pytest.raises(ComposeError) as info:
        await run_compose(script, timeline, out_dir, timeout=1.5, wrap_command=identity)
    assert "超时" in str(info.value) or "超过" in str(info.value)
    pid = int((out_dir / "child.pid").read_text())
    for _ in range(40):
        if not _alive(pid):
            break
        await asyncio.sleep(0.1)
    assert not _alive(pid)


async def test_cancellation_kills_the_script(tmp_path: Path) -> None:
    script, timeline, out_dir = _script(
        tmp_path, "import time\nopen('started','w').write('1')\ntime.sleep(60)\n"
    )
    task = asyncio.create_task(
        run_compose(script, timeline, out_dir, timeout=60, wrap_command=identity)
    )
    for _ in range(60):
        if (out_dir / "started").exists():
            break
        await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt only exists on macOS")
async def test_real_seatbelt_allows_the_run_but_not_reading_secrets_or_the_network(
    tmp_path: Path,
) -> None:
    from studio.agent.shell_sandbox import SANDBOX_EXEC, sandbox_available, seatbelt_profile

    if not sandbox_available():
        pytest.skip("sandbox-exec unavailable")
    repo_root = Path(__file__).resolve().parents[3]
    secret = repo_root / "backend" / ".env"
    workdir = tmp_path / "work"
    workdir.mkdir()
    venv = Path(sys.prefix).resolve()
    profile = seatbelt_profile(workdir, [repo_root, tmp_path / "data"]) + (
        f'(allow file-read* (subpath "{venv}"))\n'
    )

    def wrap(argv: list[str], env: dict[str, str]) -> list[str]:
        return [str(SANDBOX_EXEC), "-p", profile, *argv]

    body = (
        GOOD
        + f"""
    import socket
    try:
        open({str(secret)!r}).read(); read = "read"
    except OSError:
        read = "denied"
    try:
        socket.create_connection(("127.0.0.1", 9), timeout=1); net = "open"
    except OSError:
        net = "denied"
    import numpy
    probe = {{"secret": read, "net": net, "numpy": numpy.__version__}}
    open("probe.json", "w").write(json.dumps(probe))
    """
    )
    script = workdir / "compose.py"
    script.write_text(textwrap.dedent(body))
    timeline = workdir / "timeline.json"
    timeline.write_text(json.dumps({"duration": 1.5}))
    out_dir = workdir / ".cache" / "tmp" / "run"
    await run_compose(script, timeline, out_dir, timeout=60, wrap_command=wrap)
    probe = json.loads((out_dir / "probe.json").read_text())
    assert probe["secret"] == "denied" and probe["net"] == "denied" and probe["numpy"]
