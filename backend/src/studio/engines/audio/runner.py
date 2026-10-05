"""在临时目录里运行合成脚本并回收产物（子项目 3 设计 §7.3、§7.4）。

沙箱包装由调用方通过 `wrap_command` 传入（`engines` 不 import `agent`）。产物留在 `out_dir`，
由调用方校验通过后再移走；运行器只负责"跑起来、限时、杀干净、报错带 stderr"。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import resource
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_STDERR_TAIL_LINES = 30
_STDOUT_TAIL_CHARS = 4000
_SAFE_ENV = ("PATH", "LANG", "LC_ALL", "HOME")

WrapCommand = Callable[[list[str], dict[str, str]], list[str]]
"""`(argv, env) -> argv`：调用方把命令包装成沙箱命令；环境变量由运行器直接传给子进程。"""


class ComposeError(RuntimeError):
    """脚本失败、超时或没有写出约定的产物；消息是给 agent 看的中文，带 stderr 末尾若干行。"""


@dataclass(frozen=True, slots=True)
class RunResult:
    wav_path: Path
    events_path: Path
    stdout: str
    elapsed: float


def _tail_lines(data: bytes) -> str:
    return "\n".join(data.decode(errors="replace").strip().splitlines()[-_STDERR_TAIL_LINES:])


def _limit_cpu(seconds: int) -> Callable[[], None]:
    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 5))

    return apply


def _kill_group(process: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)


async def run_compose(
    script: Path,
    timeline_path: Path,
    out_dir: Path,
    *,
    timeout: float,
    wrap_command: WrapCommand,
) -> RunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmpdir = out_dir / "tmp"
    tmpdir.mkdir(exist_ok=True)
    wav_path, events_path = out_dir / "music.wav", out_dir / "events.json"
    env = {key: os.environ[key] for key in _SAFE_ENV if key in os.environ}
    env.update(
        STUDIO_TIMELINE=str(timeline_path),
        STUDIO_OUT_WAV=str(wav_path),
        STUDIO_OUT_EVENTS=str(events_path),
        TMPDIR=str(tmpdir),
        PYTHONDONTWRITEBYTECODE="1",
    )
    argv = wrap_command([sys.executable, str(script)], env)
    started = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=out_dir,
        env=env,
        start_new_session=True,
        preexec_fn=_limit_cpu(int(timeout) + 10),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError as exc:
        _kill_group(process)
        await process.wait()
        raise ComposeError(
            f"合成脚本运行超过 {timeout:g} 秒被终止（超时）；检查是否有死循环或过重的计算"
        ) from exc
    except BaseException:
        _kill_group(process)
        with contextlib.suppress(Exception):
            await process.wait()
        raise
    _kill_group(process)  # leftover children of a script that exited normally
    if process.returncode != 0:
        raise ComposeError(f"合成脚本失败（退出码 {process.returncode}）：\n{_tail_lines(stderr)}")
    if not wav_path.is_file():
        raise ComposeError("脚本没有写出 STUDIO_OUT_WAV 指定的 WAV 文件")
    if not events_path.is_file():
        raise ComposeError("脚本没有写出 STUDIO_OUT_EVENTS 指定的事件文件")
    return RunResult(
        wav_path=wav_path,
        events_path=events_path,
        stdout=stdout.decode(errors="replace")[-_STDOUT_TAIL_CHARS:],
        elapsed=time.monotonic() - started,
    )
