"""`CodexRuntime`：一轮 = 一个 `codex exec --json` 子进程（codex-runtime T3）。

用 `fixtures/fake_codex.py` 代替真实 CLI，回放 `fixtures/codex/` 的 JSONL。
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from studio.agent import events
from studio.agent.codex_mcp import TOKEN_ENV
from studio.agent.codex_runtime import CodexLedger, CodexRuntime, prompt_digest
from studio.agent.runtime import Budget, CancelToken, TurnContext, UserInput
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.db.repo.profiles import ModelProfileValue
from studio.workspace.scope import WriteScope

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX shell wrapper for the fake CLI"
)

FIXTURES = Path(__file__).parent / "fixtures"
SCRIPTS = FIXTURES / "codex"

PROFILE = ModelProfileValue(
    id="p-codex",
    name="codex-login",
    provider="openai",
    model="gpt-6.1-sol",
    runtime="codex",
    base_url=None,
    api_key_env=None,
    supports_vision=True,
    price_input=None,
    price_output=None,
    max_cost_per_turn=None,
    max_steps_per_turn=None,
)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    return path


def _environ(tmp_path: Path, script: str | None = None, **extra: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "home"),
        "FAKE_CODEX_RECORD": str(tmp_path / "record.json"),
        # Inherited secrets / overrides that must never reach codex.
        "OPENAI_API_KEY": "sk-should-not-leak",
        "CODEX_API_KEY": "sk-codex-should-not-leak",
        "ANTHROPIC_API_KEY": "sk-ant",
        "TAVILY_API_KEY": "tv",
        "SOME_TOKEN": "t",
    }
    if script is not None:
        env["FAKE_CODEX_SCRIPT"] = str(SCRIPTS / script)
    env.update(extra)
    return env


def _record(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))


def _ctx(
    workdir: Path,
    *,
    resume_ref: str | None = None,
    system_prompt: str | None = "阶段提示 v1",
    text: str = "你好",
    images: list[events.ImageData] | None = None,
    tools: list[ToolSpec] | None = None,
    profile: ModelProfileValue = PROFILE,
    cancel_token: CancelToken | None = None,
    exec_network: bool = False,
) -> TurnContext:
    return TurnContext(
        system_prompt=system_prompt,
        user_input=UserInput(text=text, images=images or []),
        tools=tools or [],
        workdir=workdir,
        model_profile=profile,
        resume_ref=resume_ref,
        cancel_token=cancel_token or CancelToken(),
        budget=Budget(),
        write_scope=WriteScope(writable=["topic/**"], tool_managed=[]),
        project_id="proj-1",
        stage="topic",
        record_tool_write=lambda *_: None,
        effort="medium",
        exec_network=exec_network,
    )


async def _run(runtime: CodexRuntime, ctx: TurnContext) -> list[events.AgentEvent]:
    return [event async for event in runtime.run_turn(ctx)]


def _runtime(tmp_path: Path, fake_codex_bin: Path, environ: dict[str, str]) -> CodexRuntime:
    return CodexRuntime(tmp_path / "data", fake_codex_bin, environ=environ, platform="darwin")


def _thread(script: str) -> str:
    first = (SCRIPTS / script).read_text(encoding="utf-8").splitlines()[0]
    return str(json.loads(first)["thread_id"])


async def test_new_session_turn(tmp_path: Path, fake_codex_bin: Path, workdir: Path) -> None:
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "minimal.jsonl"))
    out = await _run(runtime, _ctx(workdir))

    thread = _thread("minimal.jsonl")
    assert out[0] == events.TextBlock("ok")
    usage = out[1]
    assert isinstance(usage, events.Usage)
    assert (usage.input_tokens, usage.output_tokens, usage.auth) == (9809, 5, "login")
    assert usage.priced is False and usage.cost_usd == 0
    assert out[2] == events.TurnEnd(resume_ref=thread, status="done")

    record = _record(tmp_path)
    assert record["stdin"] == "你好"
    assert record["cwd"] == str(workdir.resolve())
    assert "resume" not in record["argv"]
    assert any(arg.startswith("developer_instructions=") for arg in record["argv"])
    for leaked in (
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "ANTHROPIC_API_KEY",
        "TAVILY_API_KEY",
        "SOME_TOKEN",
    ):
        assert leaked not in record["env"]
    assert "PATH" in record["env"] and "HOME" in record["env"]

    entry = CodexLedger(tmp_path / "data" / "codex" / "ledger").get(thread)
    assert entry is not None and entry.usage["input_tokens"] == 9809
    assert entry.prompt_digest == prompt_digest("阶段提示 v1")


async def test_resumed_turn_reports_the_difference(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    thread = _thread("minimal.jsonl")
    ledger = CodexLedger(tmp_path / "data" / "codex" / "ledger")
    ledger.record(thread, {"input_tokens": 9000, "cached_input_tokens": 0, "output_tokens": 2})
    ledger.set_prompt(thread, prompt_digest("阶段提示 v1"))
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "minimal.jsonl"))

    out = await _run(runtime, _ctx(workdir, resume_ref=thread))

    usage = next(e for e in out if isinstance(e, events.Usage))
    assert (usage.input_tokens, usage.output_tokens) == (809, 3)
    assert usage.includes_carryover is False
    argv = _record(tmp_path)["argv"]
    assert argv[argv.index("resume") + 1] == thread
    assert _record(tmp_path)["stdin"] == "你好"  # prompt unchanged: no update block


async def test_unfinished_turn_is_settled_by_the_next(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    thread = _thread("cancelled.jsonl")
    ledger = CodexLedger(tmp_path / "data" / "codex" / "ledger")
    ledger.record(thread, {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 1})

    first = await _run(
        _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "cancelled.jsonl")),
        _ctx(workdir, resume_ref=thread),
    )
    end = first[-1]
    assert isinstance(end, events.TurnEnd) and end.status == "failed"
    assert end.resume_ref == thread
    entry = ledger.get(thread)
    assert entry is not None and entry.unsettled

    # Next turn of the same thread: its cumulative total includes the lost turn.
    script = tmp_path / "next.jsonl"
    script.write_text(
        json.dumps({"type": "thread.started", "thread_id": thread})
        + "\n"
        + (SCRIPTS / "minimal.jsonl").read_text(encoding="utf-8").split("\n", 1)[1],
        encoding="utf-8",
    )
    second = await _run(
        _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, FAKE_CODEX_SCRIPT=str(script))),
        _ctx(workdir, resume_ref=thread),
    )
    usage = next(e for e in second if isinstance(e, events.Usage))
    assert usage.includes_carryover is True
    assert usage.input_tokens == 9809 - 100
    entry = ledger.get(thread)
    assert entry is not None and not entry.unsettled


async def test_model_not_found(tmp_path: Path, fake_codex_bin: Path, workdir: Path) -> None:
    runtime = _runtime(
        tmp_path, fake_codex_bin, _environ(tmp_path, "model_not_found.jsonl", FAKE_CODEX_EXIT="1")
    )
    out = await _run(runtime, _ctx(workdir))
    assert any(isinstance(e, events.Notice) for e in out)
    end = out[-1]
    assert isinstance(end, events.TurnEnd) and end.status == "failed"
    assert end.error is not None and "gpt-no-such-model" in end.error


async def test_not_logged_in(tmp_path: Path, fake_codex_bin: Path, workdir: Path) -> None:
    runtime = _runtime(
        tmp_path, fake_codex_bin, _environ(tmp_path, "not_logged_in.jsonl", FAKE_CODEX_EXIT="1")
    )
    end = (await _run(runtime, _ctx(workdir)))[-1]
    assert isinstance(end, events.TurnEnd) and end.status == "failed"
    assert end.error is not None and "codex login" in end.error


async def test_crash_without_events_reports_redacted_stderr(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    token = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVlLWhlcmU"
    stderr = f"Error: required MCP servers failed to initialize: studio (token {token})\n"
    runtime = _runtime(
        tmp_path, fake_codex_bin, _environ(tmp_path, FAKE_CODEX_STDERR=stderr, FAKE_CODEX_EXIT="2")
    )
    out = await _run(runtime, _ctx(workdir, resume_ref="th-1"))
    end = out[-1]
    assert isinstance(end, events.TurnEnd) and end.status == "failed"
    assert end.resume_ref == "th-1"
    assert end.error is not None
    assert "退出码 2" in end.error and "required MCP servers" in end.error
    assert token not in end.error


async def test_changed_system_prompt_is_sent_with_the_message(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    thread = _thread("minimal.jsonl")
    ledger = CodexLedger(tmp_path / "data" / "codex" / "ledger")
    ledger.set_prompt(thread, prompt_digest("阶段提示 v1"))
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "minimal.jsonl"))

    await _run(runtime, _ctx(workdir, resume_ref=thread, system_prompt="阶段提示 v2"))

    stdin = _record(tmp_path)["stdin"]
    assert "阶段提示 v2" in stdin and stdin.endswith("你好")
    assert stdin.index("阶段提示 v2") < stdin.index("你好")
    entry = ledger.get(thread)
    assert entry is not None and entry.prompt_digest == prompt_digest("阶段提示 v2")


def test_prompt_digest_of_the_runtime_default_is_stable() -> None:
    assert prompt_digest(None) == prompt_digest(None)
    assert prompt_digest(None) != prompt_digest("")


async def test_runtime_default_prompt_never_sends_a_prompt_update(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    """open-mode 设计 §5.1：`None` 的会话续轮时不在消息前拼 `PROMPT_UPDATE`。"""
    thread = _thread("minimal.jsonl")
    ledger = CodexLedger(tmp_path / "data" / "codex" / "ledger")
    ledger.set_prompt(thread, prompt_digest(None))
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "minimal.jsonl"))

    await _run(runtime, _ctx(workdir, resume_ref=thread, system_prompt=None))

    assert _record(tmp_path)["stdin"] == "你好"


async def test_exec_network_never_opens_the_codex_network(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    """Codex 的 `network.enabled` 连本机回环一起放开（2026-10-16 实测），
    而本机 studio API 没有认证：失败关闭，完全自由阶段在 Codex 下命令仍断网（ADR 0031 评审）。"""
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "minimal.jsonl"))

    await _run(runtime, _ctx(workdir, exec_network=True))

    argv = _record(tmp_path)["argv"]
    assert not any("network.enabled" in arg for arg in argv), argv


async def test_very_long_output_line(tmp_path: Path, fake_codex_bin: Path, workdir: Path) -> None:
    text = "长" * 700_000  # > 2 MiB in UTF-8, on one JSONL line
    script = tmp_path / "long.jsonl"
    script.write_text(
        "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "th-long"}),
                json.dumps({"type": "turn.started"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"id": "i", "type": "agent_message", "text": text},
                    }
                ),
                json.dumps(
                    {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, FAKE_CODEX_SCRIPT=str(script)))
    out = await _run(runtime, _ctx(workdir))
    assert out[0] == events.TextBlock(text)
    assert out[-1] == events.TurnEnd(resume_ref="th-long", status="done")


async def test_already_cancelled_does_not_start(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    token = CancelToken()
    token.cancel()
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "minimal.jsonl"))
    out = await _run(runtime, _ctx(workdir, resume_ref="th-9", cancel_token=token))
    assert out == [events.TurnEnd(resume_ref="th-9", status="cancelled")]
    assert not (tmp_path / "record.json").exists()


async def test_api_key_profiles_are_refused(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    profile = dataclasses.replace(PROFILE, api_key_env="OPENAI_API_KEY")
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "minimal.jsonl"))
    out = await _run(runtime, _ctx(workdir, profile=profile))
    end = out[-1]
    assert isinstance(end, events.TurnEnd) and end.status == "failed"
    assert end.error is not None and "本机登录" in end.error
    assert not (tmp_path / "record.json").exists()


async def test_images_are_passed_as_files_and_removed(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    png = events.ImageData("image/png", "iVBORw0KGgo=")
    jpeg = events.ImageData("image/jpeg", "/9j/4AAQ")
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "minimal.jsonl"))
    await _run(runtime, _ctx(workdir, images=[png, jpeg]))

    record = _record(tmp_path)
    images = [arg.split("=", 1)[1] for arg in record["argv"] if arg.startswith("--image=")]
    assert [Path(p).suffix for p in images] == [".png", ".jpg"]
    assert record["images_exist"] == [True, True]
    assert not any(Path(p).exists() for p in images)


class _NoArgs(BaseModel):
    pass


async def test_business_tools_get_a_turn_server(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    def handler(ctx: ToolContext, args: _NoArgs) -> ToolResult:
        return ToolResult(text="x")

    spec = ToolSpec("lookup", "look something up", _NoArgs, {"topic"}, handler)
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "minimal.jsonl"))
    await _run(runtime, _ctx(workdir, tools=[spec]))

    record = _record(tmp_path)
    assert TOKEN_ENV in record["env"]
    assert any(arg.startswith("mcp_servers.studio.url=") for arg in record["argv"])


def test_register_codex_only_when_the_cli_is_found(tmp_path: Path, fake_codex_bin: Path) -> None:
    from studio.agent.codex_runtime import register_codex
    from studio.agent.runtime import RuntimeFactory
    from studio.config import Settings

    found = RuntimeFactory()
    register_codex(found, Settings(data_dir=tmp_path / "data", codex_bin=fake_codex_bin))
    assert found.has("codex")

    missing = RuntimeFactory()
    register_codex(missing, Settings(data_dir=tmp_path / "data", codex_bin=tmp_path / "nope"))
    assert not missing.has("codex")


async def test_macos_turns_run_under_the_permission_profile(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    runtime = _runtime(tmp_path, fake_codex_bin, _environ(tmp_path, "minimal.jsonl"))
    await _run(runtime, _ctx(workdir))
    argv = _record(tmp_path)["argv"]
    assert 'default_permissions="studio"' in argv
    assert "-s" not in argv


async def test_without_a_sandbox_the_switch_decides(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    runtime = CodexRuntime(
        tmp_path / "data",
        fake_codex_bin,
        environ=_environ(tmp_path, "minimal.jsonl"),
        platform="linux",
    )
    refused = await _run(runtime, _ctx(workdir))
    end = refused[-1]
    assert isinstance(end, events.TurnEnd) and end.status == "failed"
    assert end.error is not None and "无隔离执行" in end.error
    assert not (tmp_path / "record.json").exists()

    allowed = await _run(runtime, dataclasses.replace(_ctx(workdir), allow_unsandboxed_exec=True))
    assert allowed[-1] == events.TurnEnd(resume_ref=_thread("minimal.jsonl"), status="done")
    argv = _record(tmp_path)["argv"]
    assert argv[argv.index("-s") + 1] == "danger-full-access"


async def test_login_failure_ends_the_turn_at_the_first_401(
    tmp_path: Path, fake_codex_bin: Path, workdir: Path
) -> None:
    """codex retries a 401 about ten times (~80 s) before `turn.failed`; the turn must not sit
    there "running" — the first auth error already says what is wrong (review Important 1)."""
    import asyncio
    import time

    lines = (SCRIPTS / "not_logged_in.jsonl").read_text(encoding="utf-8").splitlines()
    script = tmp_path / "auth.jsonl"
    script.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")  # started + first 401
    environ = _environ(
        tmp_path,
        FAKE_CODEX_SCRIPT=str(script),
        FAKE_CODEX_HANG="handle",
        FAKE_CODEX_CHILD_PID=str(tmp_path / "child.pid"),
    )
    runtime = CodexRuntime(
        tmp_path / "data", fake_codex_bin, environ=environ, platform="darwin", cancel_grace_s=2
    )
    started = time.monotonic()
    async with asyncio.timeout(20):  # without the fix the fake CLI would hang forever
        out = await _run(runtime, _ctx(workdir))
    elapsed = time.monotonic() - started

    end = out[-1]
    assert isinstance(end, events.TurnEnd) and end.status == "failed"
    assert end.error is not None and "codex login" in end.error
    assert elapsed < 6, elapsed
