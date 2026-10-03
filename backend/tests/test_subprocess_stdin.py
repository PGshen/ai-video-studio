"""子进程不得继承父进程的终端 stdin。

`make dev` 里 API 是终端的后台进程组；ffmpeg 等子进程默认继承终端作为 stdin，
启动时去读/配置终端会收到 SIGTTIN/SIGTTOU，内核会把整个进程组（uvicorn、agent CLI）
一起停住，表现为任务永远卡在"运行中"。所以每次启动子进程都必须显式给 stdin。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from studio.engines.render.manim import keyframes

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "studio"


def _subprocess_calls_without_stdin() -> list[str]:
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in {"create_subprocess_exec", "create_subprocess_shell", "Popen", "run"}:
                continue
            if name == "run" and not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                continue
            if not any(kw.arg == "stdin" for kw in node.keywords):
                offenders.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno}")
    return offenders


def test_every_subprocess_call_sets_stdin_explicitly() -> None:
    assert _subprocess_calls_without_stdin() == []


@pytest.mark.asyncio
async def test_extract_keyframe_passes_nostdin_and_devnull(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"png-bytes", b""

    async def _fake_exec(*cmd: str, **kwargs: object) -> _FakeProc:
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(keyframes.asyncio, "create_subprocess_exec", _fake_exec)

    await keyframes.extract_keyframe("/tmp/x.mp4", 1.0)

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[0] == "ffmpeg"
    assert "-nostdin" in cmd
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["stdin"] == keyframes.asyncio.subprocess.DEVNULL
