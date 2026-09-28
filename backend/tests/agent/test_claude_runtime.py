"""ClaudeRuntime 的 mock 测试：用按消息序列回放的假 SDK 客户端，不联网。"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterable, AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    Message,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk.types import HookContext, PreToolUseHookInput
from pydantic import BaseModel

from studio.agent import events
from studio.agent.claude_runtime import (
    DEFAULT_BASE_URL,
    LOGIN_BLANKED_ENV,
    ClaudeRuntime,
    build_env,
    build_sdk_tool,
    register_claude,
)
from studio.agent.runtime import Budget, CancelToken, RuntimeFactory, TurnContext, UserInput
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.config import Settings
from studio.db.repo.profiles import ModelProfileValue
from studio.workspace.scope import WriteScope

SESSION = "11111111-1111-1111-1111-111111111111"

_API_PROFILE = ModelProfileValue(
    id="p-api",
    name="claude-sonnet",
    provider="anthropic",
    model="claude-sonnet-5",
    runtime="claude",
    base_url=None,
    api_key_env="TEST_ANTHROPIC_KEY",
    supports_vision=True,
    price_input=None,
    price_output=None,
    max_cost_per_turn=None,
    max_steps_per_turn=None,
)
_LOGIN_PROFILE = dataclasses.replace(_API_PROFILE, id="p-login", api_key_env=None)
_ENVIRON = {"TEST_ANTHROPIC_KEY": "sk-test", "ANTHROPIC_API_KEY": "sk-from-shell"}


_ABORTED = object()
"""Default `interrupt_result`: an `aborted_streaming` result with a zero total."""


class FakeClient:
    """Replays `messages`; with `hold=True` it blocks after them until `interrupt()`,
    then yields `interrupt_result` (`None`: never yields a result, keeps blocking)."""

    def __init__(
        self,
        options: ClaudeAgentOptions,
        messages: list[Message],
        hold: bool,
        interrupt_result: Any = _ABORTED,
        on_connect: Callable[[], None] | None = None,
        hang_connect: bool = False,
    ) -> None:
        self.options = options
        self.hang_connect = hang_connect
        self.connect_cancelled = False
        self.messages = messages
        self.hold = hold
        self.interrupt_result = interrupt_result
        self.on_connect = on_connect
        self.prompts: list[Any] = []
        self.interrupted = asyncio.Event()
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        self.connected = True
        if self.on_connect is not None:
            self.on_connect()
        if self.hang_connect:  # e.g. a CLI that never finishes initialising
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.connect_cancelled = True
                raise

    async def query(self, prompt: str | AsyncIterable[dict[str, Any]]) -> None:
        if isinstance(prompt, str):
            self.prompts.append(prompt)
        else:
            self.prompts.append([message async for message in prompt])

    async def receive_response(self) -> AsyncIterator[Message]:
        for message in self.messages:
            yield message
            await asyncio.sleep(0)
        if self.hold:
            await self.interrupted.wait()
            if self.interrupt_result is None:
                await asyncio.Event().wait()  # the CLI never answers
            elif self.interrupt_result is _ABORTED:
                yield _result(0.0, terminal_reason="aborted_streaming")
            else:
                yield self.interrupt_result

    async def interrupt(self) -> None:
        self.interrupted.set()

    async def disconnect(self) -> None:
        self.disconnected = True


class Clients:
    """Client factory that records every client it creates."""

    def __init__(
        self,
        messages: list[Message] | None = None,
        *,
        hold: bool = False,
        interrupt_result: Any = _ABORTED,
        on_connect: Callable[[], None] | None = None,
        hang_connect: bool = False,
    ) -> None:
        self.hang_connect = hang_connect
        self.messages = messages or [_result(0.0)]
        self.hold = hold
        self.interrupt_result = interrupt_result
        self.on_connect = on_connect
        self.created: list[FakeClient] = []

    def __call__(self, options: ClaudeAgentOptions) -> FakeClient:
        client = FakeClient(
            options,
            self.messages,
            self.hold,
            self.interrupt_result,
            self.on_connect,
            self.hang_connect,
        )
        self.created.append(client)
        return client

    @property
    def last(self) -> FakeClient:
        return self.created[-1]


def _result(
    total_cost_usd: float | None,
    *,
    subtype: str = "success",
    is_error: bool = False,
    usage: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    terminal_reason: str | None = "completed",
    session_id: str = SESSION,
) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=total_cost_usd,
        usage=usage,
        errors=errors,
        terminal_reason=terminal_reason,
    )


def _assistant(*blocks: Any) -> AssistantMessage:
    return AssistantMessage(content=list(blocks), model="claude-sonnet-5", session_id=SESSION)


def _base64_source(media_type: str, data: str) -> dict[str, str]:
    return {"type": "base64", "media_type": media_type, "data": data}


def _noop_record(relpath: str, sha256: str) -> None:
    return None


def _ctx(
    workdir: Path,
    *,
    profile: ModelProfileValue = _API_PROFILE,
    resume_ref: str | None = None,
    budget: Budget | None = None,
    cancel_token: CancelToken | None = None,
    tools: list[ToolSpec] | None = None,
    allow_web: bool = False,
    user_input: UserInput | None = None,
    record_tool_write: Callable[[str, str], None] = _noop_record,
) -> TurnContext:
    return TurnContext(
        system_prompt="系统提示词",
        user_input=user_input or UserInput(text="你好"),
        tools=tools or [],
        workdir=workdir,
        model_profile=profile,
        resume_ref=resume_ref,
        cancel_token=cancel_token or CancelToken(),
        budget=budget or Budget(),
        write_scope=WriteScope(writable=["topic/**"], tool_managed=["topic/managed.json"]),
        project_id="proj-1",
        stage="topic",
        record_tool_write=record_tool_write,
        allow_web=allow_web,
    )


def _runtime(data_dir: Path, clients: Clients) -> ClaudeRuntime:
    return ClaudeRuntime(data_dir, client_factory=clients, environ=_ENVIRON)


async def _run(runtime: ClaudeRuntime, ctx: TurnContext) -> list[events.AgentEvent]:
    return [event async for event in runtime.run_turn(ctx)]


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


class _Args(BaseModel):
    text: str


def _echo_spec(handler: Callable[[ToolContext, _Args], ToolResult] | None = None) -> ToolSpec:
    def echo(_ctx: ToolContext, args: _Args) -> ToolResult:
        return ToolResult(text=args.text)

    return ToolSpec("echo", "回显", _Args, {"topic"}, handler or echo)


class TestOptions:
    async def test_core_options(self, workdir: Path, data_dir: Path) -> None:
        clients = Clients()
        await _run(_runtime(data_dir, clients), _ctx(workdir, resume_ref=SESSION))

        options = clients.last.options
        assert options.model == "claude-sonnet-5"
        assert options.cwd == workdir
        assert options.system_prompt == "系统提示词"
        assert options.setting_sources == []
        assert options.permission_mode == "acceptEdits"
        assert options.resume == SESSION
        assert options.include_partial_messages is True
        assert options.tools == ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
        assert options.sandbox is not None and options.sandbox.get("enabled") is True
        assert options.hooks is not None and "PreToolUse" in options.hooks
        assert clients.last.prompts == ["你好"]
        assert clients.last.disconnected

    async def test_web_tools_only_when_allowed(self, workdir: Path, data_dir: Path) -> None:
        clients = Clients()
        await _run(_runtime(data_dir, clients), _ctx(workdir, allow_web=True))

        tools = clients.last.options.tools
        assert isinstance(tools, list)
        assert "WebSearch" in tools and "WebFetch" in tools
        assert "WebSearch" in clients.last.options.allowed_tools

    async def test_business_tools_become_mcp_server(self, workdir: Path, data_dir: Path) -> None:
        clients = Clients()
        await _run(_runtime(data_dir, clients), _ctx(workdir, tools=[_echo_spec()]))

        options = clients.last.options
        assert isinstance(options.mcp_servers, dict)
        assert options.mcp_servers["studio"].get("type") == "sdk"
        assert "mcp__studio__echo" in options.allowed_tools

    async def test_user_images_sent_as_content_blocks(self, workdir: Path, data_dir: Path) -> None:
        clients = Clients()
        user_input = UserInput(text="看图", images=[events.ImageData("image/png", "aGk=")])
        await _run(_runtime(data_dir, clients), _ctx(workdir, user_input=user_input))

        (sent,) = clients.last.prompts
        content = sent[0]["message"]["content"]
        assert content[0] == {"type": "text", "text": "看图"}
        assert content[1]["source"] == {"type": "base64", "media_type": "image/png", "data": "aGk="}


class TestAuth:
    async def test_api_key_mode_injects_key_and_config_dir(
        self, workdir: Path, data_dir: Path
    ) -> None:
        clients = Clients()
        profile = dataclasses.replace(_API_PROFILE, base_url="https://proxy.example")
        await _run(_runtime(data_dir, clients), _ctx(workdir, profile=profile))

        env = clients.last.options.env
        assert env["ANTHROPIC_API_KEY"] == "sk-test"
        assert env["ANTHROPIC_BASE_URL"] == "https://proxy.example"
        assert env["CLAUDE_CONFIG_DIR"] == str(data_dir / "claude")

    async def test_login_mode_blanks_key_and_keeps_config_dir(
        self, workdir: Path, data_dir: Path
    ) -> None:
        clients = Clients([_result(0.2)])
        result = await _run(_runtime(data_dir, clients), _ctx(workdir, profile=_LOGIN_PROFILE))

        env = clients.last.options.env
        # The SDK merges `env` over os.environ, so blanking is the only way to drop a key;
        # the CLI treats an empty value as unset.
        effective = {**_ENVIRON, **env}
        for name in LOGIN_BLANKED_ENV:
            assert effective.get(name, "") == ""
        assert "ANTHROPIC_API_KEY" in LOGIN_BLANKED_ENV
        assert "CLAUDE_CONFIG_DIR" not in env
        usage = next(e for e in result if isinstance(e, events.Usage))
        assert usage.auth == "login"

    async def test_missing_key_fails_turn_without_starting_sdk(
        self, workdir: Path, data_dir: Path
    ) -> None:
        clients = Clients()
        profile = dataclasses.replace(_API_PROFILE, api_key_env="NOT_SET_KEY")

        result = await _run(_runtime(data_dir, clients), _ctx(workdir, profile=profile))

        assert clients.created == []
        (end,) = result
        assert isinstance(end, events.TurnEnd)
        assert end.status == "failed"
        assert end.error is not None and "NOT_SET_KEY" in end.error


# What a Claude Code / Claude desktop shell exports (values are dummies).
_HOST_ENVIRON = {
    "HOME": "/Users/me",
    "PATH": "/usr/bin",
    "ANTHROPIC_BASE_URL": "https://host-proxy.example",
    "ANTHROPIC_AUTH_TOKEN": "host-token",
    "ANTHROPIC_MODEL": "claude-opus-5",
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "CLAUDE_CODE_USE_VERTEX": "1",
    "CLAUDE_CODE_OAUTH_TOKEN": "host-oauth",
    "CLAUDE_CODE_OAUTH_SCOPES": "user:inference",
    "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH": "1",
    "CLAUDE_CODE_HOST_SESSION_ID": "h1",
    "CLAUDE_CODE_SESSION_ID": "s1",
    "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/sock",
    "CLAUDE_CODE_MESSAGING_TOKEN": "t",
    "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING": "true",
    "CLAUDE_CODE_EXECPATH": "/Applications/Claude.app/claude",
    # Must survive: the SDK sets these itself, or the user chose them.
    "CLAUDE_CODE_ENTRYPOINT": "claude-desktop",
    "CLAUDE_CODE_SDK_READS_SESSION_STATE": "1",
    "CLAUDE_CONFIG_DIR": "/Users/me/.claude-work",
}
_HOST_ONLY = sorted(
    set(_HOST_ENVIRON)
    - {
        "HOME",
        "PATH",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_SDK_READS_SESSION_STATE",
        "CLAUDE_CONFIG_DIR",
    }
)


class TestBuildEnv:
    @pytest.mark.parametrize("api_key_env", [None, "MY_KEY"])
    def test_host_auth_and_target_vars_are_neutralised(
        self, api_key_env: str | None, tmp_path: Path
    ) -> None:
        environ = {**_HOST_ENVIRON, "MY_KEY": "sk-mine"}
        _auth, env = build_env(api_key_env, None, environ, tmp_path / "claude")
        effective = {**environ, **env}
        for name in _HOST_ONLY:
            assert effective[name] == "", name
        # A blank ANTHROPIC_BASE_URL is not "unset" everywhere in the CLI (`??`), so the
        # host proxy is replaced by the public endpoint instead.
        assert effective["ANTHROPIC_BASE_URL"] == DEFAULT_BASE_URL
        assert effective["CLAUDE_CODE_SDK_READS_SESSION_STATE"] == "1"
        assert "CLAUDE_CODE_ENTRYPOINT" not in env
        assert "HOME" not in env and "PATH" not in env

    def test_login_mode_keeps_config_dir_and_blanks_keys(self, tmp_path: Path) -> None:
        environ = {**_HOST_ENVIRON, "ANTHROPIC_API_KEY": "sk-leak"}
        auth, env = build_env(None, None, environ, tmp_path / "claude")
        assert auth == "login"
        effective = {**environ, **env}
        assert effective["ANTHROPIC_API_KEY"] == ""
        assert effective["CLAUDE_CONFIG_DIR"] == "/Users/me/.claude-work"

    def test_api_key_mode_uses_profile_key_and_data_dir(self, tmp_path: Path) -> None:
        environ = {**_HOST_ENVIRON, "MY_KEY": "sk-mine", "ANTHROPIC_API_KEY": "sk-other"}
        auth, env = build_env("MY_KEY", None, environ, tmp_path / "claude")
        assert auth == "api_key"
        assert env["ANTHROPIC_API_KEY"] == "sk-mine"
        assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "claude")

    def test_profile_base_url_wins(self, tmp_path: Path) -> None:
        _auth, env = build_env(None, "https://mine.example", _HOST_ENVIRON, tmp_path)
        assert env["ANTHROPIC_BASE_URL"] == "https://mine.example"

    @pytest.mark.parametrize("api_key_env", [None, "MY_KEY"])
    def test_unrelated_secrets_are_blanked(self, api_key_env: str | None, tmp_path: Path) -> None:
        environ = {
            **_HOST_ENVIRON,
            "MY_KEY": "sk-mine",
            "OPENAI_API_KEY": "sk-openai",
            "DEEPSEEK_API_KEY": "sk-deepseek",
            "GITHUB_TOKEN": "ghp",
            "AWS_SECRET_ACCESS_KEY": "aws",
            "DB_PASSWORD": "pw",
            "tavily_api_key": "tv",
            # Must survive: not secrets, even though they contain similar letters.
            "SSH_AUTH_SOCK": "/tmp/ssh",
            "KEYCHAIN_PROFILE": "default",
            "MONKEY_BUSINESS": "1",
        }
        _auth, env = build_env(api_key_env, None, environ, tmp_path / "claude")
        effective = {**environ, **env}
        for name in (
            "MY_KEY",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "GITHUB_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
            "DB_PASSWORD",
            "tavily_api_key",
        ):
            assert effective[name] == "", name
        for name in ("SSH_AUTH_SOCK", "KEYCHAIN_PROFILE", "MONKEY_BUSINESS", "HOME", "PATH"):
            assert name not in env, name
        if api_key_env is not None:
            assert effective["ANTHROPIC_API_KEY"] == "sk-mine"

    def test_clean_environment_adds_only_what_is_needed(self, tmp_path: Path) -> None:
        _auth, env = build_env(None, None, {"HOME": "/Users/me"}, tmp_path)
        assert env == dict.fromkeys(LOGIN_BLANKED_ENV, "")


class TestEventConversion:
    async def test_full_turn(self, workdir: Path, data_dir: Path) -> None:
        messages: list[Message] = [
            SystemMessage(subtype="init", data={"session_id": SESSION}),
            StreamEvent(
                uuid="u1",
                session_id=SESSION,
                event={
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "好"},
                },
            ),
            _assistant(
                TextBlock(text="好的"),
                ToolUseBlock(id="t1", name="Write", input={"file_path": "topic/a.md"}),
                ToolUseBlock(id="t2", name="mcp__studio__echo", input={"text": "x"}),
            ),
            UserMessage(
                content=[
                    ToolResultBlock(tool_use_id="t1", content="写好了", is_error=False),
                    ToolResultBlock(
                        tool_use_id="t2",
                        content=[
                            {"type": "text", "text": "图"},
                            {"type": "image", "source": _base64_source("image/png", "QQ==")},
                            {"type": "image", "data": "Qg==", "mimeType": "image/jpeg"},
                        ],
                    ),
                ]
            ),
            _result(
                0.5,
                usage={
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 5,
                    "cache_read_input_tokens": 3,
                    "output_tokens": 7,
                },
            ),
        ]
        result = await _run(_runtime(data_dir, Clients(messages)), _ctx(workdir))

        assert result == [
            events.TextDelta(text="好"),
            events.TextBlock(text="好的"),
            events.ToolCall(call_id="t1", name="Write", args={"file_path": "topic/a.md"}),
            events.ToolCall(call_id="t2", name="echo", args={"text": "x"}),
            events.ToolResult(call_id="t1", text="写好了"),
            events.ToolResult(
                call_id="t2",
                text="图",
                images=[
                    events.ImageData("image/png", "QQ=="),
                    events.ImageData("image/jpeg", "Qg=="),
                ],
            ),
            events.Usage(input_tokens=18, output_tokens=7, cost_usd=0.5, auth="api_key"),
            events.TurnEnd(resume_ref=SESSION, status="done"),
        ]

    async def test_native_write_tools_are_file_tools(self) -> None:
        for name in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"):
            assert name in events.FILE_TOOL_NAMES

    async def test_error_result_fails_turn(self, workdir: Path, data_dir: Path) -> None:
        messages: list[Message] = [
            _result(0.1, subtype="error_during_execution", is_error=True, errors=["炸了"])
        ]
        result = await _run(_runtime(data_dir, Clients(messages)), _ctx(workdir))

        end = result[-1]
        assert isinstance(end, events.TurnEnd)
        assert end.status == "failed" and end.error is not None and "炸了" in end.error
        assert end.resume_ref == SESSION

    async def test_sdk_exception_fails_turn(self, workdir: Path, data_dir: Path) -> None:
        class Broken(Clients):
            def __call__(self, options: ClaudeAgentOptions) -> FakeClient:
                client = super().__call__(options)

                async def connect() -> None:
                    raise RuntimeError("CLI 不见了")

                client.connect = connect
                return client

        clients = Broken()
        result = await _run(_runtime(data_dir, clients), _ctx(workdir, resume_ref=SESSION))

        (end,) = result
        assert isinstance(end, events.TurnEnd)
        assert end.status == "failed" and end.error is not None and "CLI 不见了" in end.error
        assert end.resume_ref == SESSION
        assert clients.last.disconnected

    async def test_client_factory_exception_fails_turn(self, workdir: Path, data_dir: Path) -> None:
        def broken_factory(options: ClaudeAgentOptions) -> FakeClient:
            raise RuntimeError("找不到 CLI")

        runtime = ClaudeRuntime(data_dir, client_factory=broken_factory, environ=_ENVIRON)
        result = await _run(runtime, _ctx(workdir, resume_ref=SESSION))

        (end,) = result
        assert isinstance(end, events.TurnEnd)
        assert end.status == "failed" and end.error is not None and "找不到 CLI" in end.error
        assert end.resume_ref == SESSION

    async def test_image_block_without_mime_type_is_skipped(
        self, workdir: Path, data_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        messages: list[Message] = [
            UserMessage(
                content=[
                    ToolResultBlock(
                        tool_use_id="t1",
                        content=[
                            {"type": "text", "text": "ok"},
                            {"type": "image", "data": "AAAA"},
                            {"type": "image", "mimeType": "image/png", "data": "BBBB"},
                        ],
                    )
                ]
            ),
            _result(0.0),
        ]
        result = await _run(_runtime(data_dir, Clients(messages)), _ctx(workdir))

        (tool_result,) = [e for e in result if isinstance(e, events.ToolResult)]
        assert tool_result.text == "ok"
        assert tool_result.images == [events.ImageData("image/png", "BBBB")]
        assert "图片" in caplog.text


class TestUsageDelta:
    async def test_resumed_session_reports_per_turn_delta(
        self, workdir: Path, data_dir: Path
    ) -> None:
        first = await _run(_runtime(data_dir, Clients([_result(0.5)])), _ctx(workdir))
        # A fresh runtime instance: the previous total must survive a process restart.
        second = await _run(
            _runtime(data_dir, Clients([_result(0.8)])), _ctx(workdir, resume_ref=SESSION)
        )

        assert [e.cost_usd for e in first if isinstance(e, events.Usage)] == [0.5]
        assert [e.cost_usd for e in second if isinstance(e, events.Usage)] == [pytest.approx(0.3)]

    async def test_total_lower_than_recorded_is_taken_as_fresh(
        self, workdir: Path, data_dir: Path
    ) -> None:
        await _run(_runtime(data_dir, Clients([_result(0.5)])), _ctx(workdir))
        second = await _run(
            _runtime(data_dir, Clients([_result(0.2)])), _ctx(workdir, resume_ref=SESSION)
        )

        assert [e.cost_usd for e in second if isinstance(e, events.Usage)] == [0.2]

    async def test_new_session_ignores_ledger(self, workdir: Path, data_dir: Path) -> None:
        await _run(_runtime(data_dir, Clients([_result(0.5)])), _ctx(workdir))
        again = await _run(_runtime(data_dir, Clients([_result(0.7)])), _ctx(workdir))

        assert [e.cost_usd for e in again if isinstance(e, events.Usage)] == [0.7]


class TestSdkTool:
    async def test_handler_goes_through_invoke_tool_with_ctx(self, workdir: Path) -> None:
        seen: list[ToolContext] = []

        def handler(tool_ctx: ToolContext, args: _Args) -> ToolResult:
            seen.append(tool_ctx)
            return ToolResult(
                text=f"echo {args.text}", images=[events.ImageData("image/png", "QQ==")]
            )

        ctx = _ctx(workdir)
        sdk_tool = build_sdk_tool(_echo_spec(handler), ctx)
        output = await sdk_tool.handler({"text": "hi"})

        assert output == {
            "content": [
                {"type": "text", "text": "echo hi"},
                {"type": "image", "data": "QQ==", "mimeType": "image/png"},
            ],
            "is_error": False,
        }
        assert seen[0].project_id == "proj-1" and seen[0].workdir == workdir
        assert seen[0].record_tool_write is ctx.record_tool_write
        assert sdk_tool.name == "echo"
        assert isinstance(sdk_tool.input_schema, dict)
        assert sdk_tool.input_schema["properties"]["text"]["type"] == "string"

    async def test_invalid_args_become_error_result(self, workdir: Path) -> None:
        sdk_tool = build_sdk_tool(_echo_spec(), _ctx(workdir))
        output = await sdk_tool.handler({})
        assert output["is_error"] is True


class TestWriteScopeHook:
    async def _decide(
        self, workdir: Path, data_dir: Path, tool_name: str, tool_input: dict[str, Any]
    ) -> dict[str, Any]:
        clients = Clients()
        await _run(_runtime(data_dir, clients), _ctx(workdir))
        hooks = clients.last.options.hooks
        assert hooks is not None
        (matcher,) = [
            m
            for m in hooks["PreToolUse"]
            if m.matcher is not None and tool_name in m.matcher.split("|")
        ]
        hook_input: PreToolUseHookInput = {
            "session_id": SESSION,
            "transcript_path": "",
            "cwd": str(workdir),
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_use_id": "t1",
        }
        context: HookContext = {"signal": None}
        output = await matcher.hooks[0](hook_input, "t1", context)
        return dict(output)

    async def test_write_inside_scope_allowed(self, workdir: Path, data_dir: Path) -> None:
        output = await self._decide(
            workdir, data_dir, "Write", {"file_path": str(workdir / "topic" / "brief.md")}
        )
        assert "hookSpecificOutput" not in output

    async def test_relative_path_inside_scope_allowed(self, workdir: Path, data_dir: Path) -> None:
        output = await self._decide(workdir, data_dir, "Edit", {"file_path": "topic/brief.md"})
        assert "hookSpecificOutput" not in output

    @pytest.mark.parametrize(
        ("tool_name", "tool_input"),
        [
            ("Write", {"file_path": "style/STYLE.md"}),
            ("Edit", {"file_path": "topic/managed.json"}),
            ("MultiEdit", {"file_path": "../outside.md"}),
            ("NotebookEdit", {"notebook_path": "/etc/x.ipynb"}),
            ("Write", {"file_path": "upstream/topic/brief.md"}),
            ("Write", {}),
            # Claude Code file tools expand a leading `~` (F1).
            ("Write", {"file_path": "~/topic/brief.md"}),
            ("Edit", {"file_path": "~root/.bashrc"}),
            ("NotebookEdit", {"notebook_path": "~"}),
            # The CLI trims paths before expanding them.
            ("Write", {"file_path": " ~/topic/brief.md"}),
            ("Edit", {"file_path": "\t/etc/hosts"}),
            ("Write", {"file_path": " topic/brief.md"}),
            ("Write", {"file_path": "topic/brief.md "}),
            ("Write", {"file_path": "\ufefftopic/brief.md"}),
        ],
    )
    async def test_out_of_scope_denied(
        self, workdir: Path, data_dir: Path, tool_name: str, tool_input: dict[str, Any]
    ) -> None:
        output = await self._decide(workdir, data_dir, tool_name, tool_input)
        specific = output["hookSpecificOutput"]
        assert specific["hookEventName"] == "PreToolUse"
        assert specific["permissionDecision"] == "deny"
        assert specific["permissionDecisionReason"]


class TestReadScopeHook:
    _decide = TestWriteScopeHook._decide

    @pytest.mark.parametrize(
        ("tool_name", "tool_input"),
        [
            ("Read", {"file_path": "topic/brief.md"}),
            ("Read", {"file_path": "upstream/topic/brief.md"}),
            ("Read", {"file_path": "style/STYLE.md"}),
            ("Glob", {"pattern": "**/*.md"}),
            ("Glob", {"pattern": "*.md", "path": "topic"}),
            ("Grep", {"pattern": "foo"}),
            ("Grep", {"pattern": "foo", "path": ".", "glob": "*.md"}),
        ],
    )
    async def test_inside_workspace_allowed(
        self, workdir: Path, data_dir: Path, tool_name: str, tool_input: dict[str, Any]
    ) -> None:
        output = await self._decide(workdir, data_dir, tool_name, tool_input)
        assert "hookSpecificOutput" not in output

    async def test_absolute_path_inside_workspace_allowed(
        self, workdir: Path, data_dir: Path
    ) -> None:
        output = await self._decide(
            workdir, data_dir, "Read", {"file_path": str(workdir / "topic" / "brief.md")}
        )
        assert "hookSpecificOutput" not in output

    @pytest.mark.parametrize(
        ("tool_name", "tool_input"),
        [
            ("Read", {"file_path": "/etc/passwd"}),
            ("Read", {"file_path": "../../backend/.env"}),
            ("Read", {}),
            ("Glob", {"pattern": "*", "path": "/Users"}),
            ("Glob", {"pattern": "../**/.env"}),
            ("Glob", {"pattern": "/Users/**/.env"}),
            ("Grep", {"pattern": "KEY", "path": ".."}),
            ("Grep", {"pattern": "KEY", "glob": "../**"}),
            # Claude Code file tools expand a leading `~` (F1).
            ("Read", {"file_path": "~"}),
            ("Read", {"file_path": "~/.ssh/id_rsa"}),
            ("Read", {"file_path": "~root/x"}),
            ("Glob", {"pattern": "*", "path": "~/.aws"}),
            ("Glob", {"pattern": "~root/**"}),
            ("Grep", {"pattern": "KEY", "path": "~"}),
            ("Grep", {"pattern": "KEY", "path": "~root/x"}),
            ("Grep", {"pattern": "KEY", "glob": "~/**"}),
            # The CLI trims paths before expanding them.
            ("Read", {"file_path": " /etc/passwd"}),
            ("Read", {"file_path": " ~/.ssh/id_rsa"}),
            ("Read", {"file_path": "\t~/.ssh/id_rsa"}),
            ("Read", {"file_path": " ../../x"}),
            ("Read", {"file_path": "topic/brief.md\n"}),
            ("Read", {"file_path": "\u00a0~/.ssh/id_rsa"}),
            ("Grep", {"pattern": "KEY", "path": " ~"}),
            ("Grep", {"pattern": "KEY", "glob": " /etc/*"}),
            ("Glob", {"pattern": " /etc/*"}),
            ("Glob", {"pattern": "*", "path": "\t/Users"}),
        ],
    )
    async def test_outside_workspace_denied(
        self, workdir: Path, data_dir: Path, tool_name: str, tool_input: dict[str, Any]
    ) -> None:
        output = await self._decide(workdir, data_dir, tool_name, tool_input)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    async def test_symlink_escaping_workspace_denied(
        self, workdir: Path, data_dir: Path, tmp_path: Path
    ) -> None:
        secret = tmp_path / "secret.env"
        secret.write_text("KEY=1", encoding="utf-8")
        (workdir / "topic").mkdir(parents=True, exist_ok=True)
        (workdir / "topic" / "link.md").symlink_to(secret)

        output = await self._decide(workdir, data_dir, "Read", {"file_path": "topic/link.md"})

        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestCancelAndBudget:
    async def test_cancel_calls_interrupt(self, workdir: Path, data_dir: Path) -> None:
        clients = Clients([_assistant(TextBlock(text="开始"))], hold=True)
        token = CancelToken()
        ctx = _ctx(workdir, cancel_token=token)

        received: list[events.AgentEvent] = []
        async for event in _runtime(data_dir, clients).run_turn(ctx):
            received.append(event)
            if isinstance(event, events.TextBlock):
                token.cancel()

        assert clients.last.interrupted.is_set()
        assert received[-1] == events.TurnEnd(resume_ref=SESSION, status="cancelled")
        assert clients.last.disconnected

    async def test_step_budget_is_left_to_the_runner(self, workdir: Path, data_dir: Path) -> None:
        """TD-18: the runner counts steps and stops the turn via the cancel token."""
        clients = Clients(
            [
                _assistant(ToolUseBlock(id="t1", name="Read", input={})),
                _assistant(ToolUseBlock(id="t2", name="Read", input={})),
                _result(0.0),
            ]
        )
        result = await _run(_runtime(data_dir, clients), _ctx(workdir, budget=Budget(max_steps=1)))

        assert not clients.last.interrupted.is_set()
        assert result[-1] == events.TurnEnd(resume_ref=SESSION, status="done")

    async def test_cancel_after_tool_call_interrupts(self, workdir: Path, data_dir: Path) -> None:
        clients = Clients([_assistant(ToolUseBlock(id="t1", name="Read", input={}))], hold=True)
        token = CancelToken()

        received: list[events.AgentEvent] = []
        async for event in _runtime(data_dir, clients).run_turn(_ctx(workdir, cancel_token=token)):
            received.append(event)
            if isinstance(event, events.ToolCall):
                token.cancel()

        assert clients.last.interrupted.is_set()
        assert received[-1] == events.TurnEnd(resume_ref=SESSION, status="cancelled")

    async def test_cost_budget_uses_sdk_limit(self, workdir: Path, data_dir: Path) -> None:
        clients = Clients([_result(1.2, subtype="error_max_budget_usd", is_error=True)])
        result = await _run(
            _runtime(data_dir, clients), _ctx(workdir, budget=Budget(max_cost_usd=1.0))
        )

        assert clients.last.options.max_budget_usd == 1.0
        assert result[-1] == events.TurnEnd(resume_ref=SESSION, status="budget_exceeded")

    async def test_login_mode_does_not_enforce_cost(self, workdir: Path, data_dir: Path) -> None:
        clients = Clients()
        await _run(
            _runtime(data_dir, clients),
            _ctx(workdir, profile=_LOGIN_PROFILE, budget=Budget(max_cost_usd=1.0)),
        )
        assert clients.last.options.max_budget_usd is None


def _costs(result: list[events.AgentEvent]) -> list[tuple[float, bool]]:
    return [(e.cost_usd, e.includes_carryover) for e in result if isinstance(e, events.Usage)]


class TestCancelBeforeSdk:
    """TD-12: cancellation during setup ends the turn at once, without waiting for
    the runner's grace period; a zero cost budget never starts the model."""

    async def test_cancelled_before_connect_does_not_start_sdk(
        self, workdir: Path, data_dir: Path
    ) -> None:
        clients = Clients()
        token = CancelToken()
        token.cancel()

        result = await _run(
            _runtime(data_dir, clients), _ctx(workdir, resume_ref=SESSION, cancel_token=token)
        )

        assert clients.created == []
        assert result == [events.TurnEnd(resume_ref=SESSION, status="cancelled")]

    async def test_cancelled_during_connect_ends_without_query(
        self, workdir: Path, data_dir: Path
    ) -> None:
        token = CancelToken()
        clients = Clients(on_connect=token.cancel)

        result = await asyncio.wait_for(
            _run(
                _runtime(data_dir, clients),
                _ctx(workdir, resume_ref=SESSION, cancel_token=token),
            ),
            timeout=1,
        )

        assert clients.last.connected and clients.last.prompts == []
        assert clients.last.disconnected
        assert result == [events.TurnEnd(resume_ref=SESSION, status="cancelled")]

    async def test_cancel_while_connect_hangs_ends_at_once(
        self, workdir: Path, data_dir: Path
    ) -> None:
        token = CancelToken()
        clients = Clients(on_connect=token.cancel, hang_connect=True)

        result = await asyncio.wait_for(
            _run(
                _runtime(data_dir, clients),
                _ctx(workdir, resume_ref=SESSION, cancel_token=token),
            ),
            timeout=1,
        )

        assert clients.last.connect_cancelled and clients.last.prompts == []
        assert result == [events.TurnEnd(resume_ref=SESSION, status="cancelled")]

    @pytest.mark.parametrize("profile", [_API_PROFILE, _LOGIN_PROFILE], ids=["api", "login"])
    async def test_zero_cost_budget_is_refused(
        self, profile: ModelProfileValue, workdir: Path, data_dir: Path
    ) -> None:
        clients = Clients()

        result = await _run(
            _runtime(data_dir, clients),
            _ctx(workdir, profile=profile, resume_ref=SESSION, budget=Budget(max_cost_usd=0)),
        )

        assert clients.created == []
        (end,) = result
        assert isinstance(end, events.TurnEnd)
        assert (end.status, end.resume_ref) == ("budget_exceeded", SESSION)
        assert end.error is not None


class TestCancelledTurnCost:
    """TD-11: a cancelled turn's spend is neither counted twice nor silently lost."""

    async def test_cancel_with_result_records_its_own_cost(
        self, workdir: Path, data_dir: Path
    ) -> None:
        await _run(_runtime(data_dir, Clients([_result(0.5)])), _ctx(workdir))
        token = CancelToken()
        clients = Clients(
            [_assistant(TextBlock(text="开始"))],
            hold=True,
            interrupt_result=_result(0.7, terminal_reason="aborted_streaming"),
        )
        cancelled: list[events.AgentEvent] = []
        async for event in _runtime(data_dir, clients).run_turn(
            _ctx(workdir, resume_ref=SESSION, cancel_token=token)
        ):
            cancelled.append(event)
            if isinstance(event, events.TextBlock):
                token.cancel()
        after = await _run(
            _runtime(data_dir, Clients([_result(0.9)])), _ctx(workdir, resume_ref=SESSION)
        )

        assert cancelled[-1] == events.TurnEnd(resume_ref=SESSION, status="cancelled")
        assert _costs(cancelled) == [(pytest.approx(0.2), False)]
        assert _costs(after) == [(pytest.approx(0.2), False)]

    async def test_force_cancelled_turn_is_carried_into_next_turn(
        self, workdir: Path, data_dir: Path
    ) -> None:
        await _run(_runtime(data_dir, Clients([_result(0.5)])), _ctx(workdir))
        token = CancelToken()
        clients = Clients(
            [SystemMessage(subtype="init", data={"session_id": SESSION})],
            hold=True,
            interrupt_result=None,
        )

        async def consume() -> list[events.AgentEvent]:
            return await _run(
                _runtime(data_dir, clients), _ctx(workdir, resume_ref=SESSION, cancel_token=token)
            )

        # Like TurnRunner: set the token, then force-cancel the task after the grace period.
        task = asyncio.create_task(consume())
        while not (clients.created and clients.last.prompts):  # the query has been sent
            await asyncio.sleep(0)
        token.cancel()
        await clients.last.interrupted.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert clients.last.disconnected

        next_turn = await _run(
            _runtime(data_dir, Clients([_result(1.0)])), _ctx(workdir, resume_ref=SESSION)
        )
        settled = await _run(
            _runtime(data_dir, Clients([_result(1.1)])), _ctx(workdir, resume_ref=SESSION)
        )

        # The unsettled spend (1.0 - 0.5) shows up once, flagged, in the next turn.
        assert _costs(next_turn) == [(pytest.approx(0.5), True)]
        assert _costs(settled) == [(pytest.approx(0.1), False)]

    async def test_failed_turn_without_result_is_carried_too(
        self, workdir: Path, data_dir: Path
    ) -> None:
        await _run(_runtime(data_dir, Clients([_result(0.5)])), _ctx(workdir))
        # No result message at all (e.g. the CLI died mid-turn).
        broken = await _run(
            _runtime(data_dir, Clients([_assistant(TextBlock(text="半"))])),
            _ctx(workdir, resume_ref=SESSION),
        )
        next_turn = await _run(
            _runtime(data_dir, Clients([_result(0.8)])), _ctx(workdir, resume_ref=SESSION)
        )

        assert isinstance(broken[-1], events.TurnEnd) and broken[-1].status == "failed"
        assert _costs(next_turn) == [(pytest.approx(0.3), True)]


class TestLedgerKey:
    """TD-11: the ledger is keyed by the SDK session id of the result."""

    async def test_result_session_entry_is_used_when_present(
        self, workdir: Path, data_dir: Path
    ) -> None:
        other = "22222222-2222-2222-2222-222222222222"
        await _run(_runtime(data_dir, Clients([_result(0.5)])), _ctx(workdir))
        await _run(_runtime(data_dir, Clients([_result(0.6, session_id=other)])), _ctx(workdir))

        result = await _run(
            _runtime(data_dir, Clients([_result(0.8, session_id=other)])),
            _ctx(workdir, resume_ref=SESSION),
        )

        assert _costs(result) == [(pytest.approx(0.2), False)]

    async def test_unknown_result_session_falls_back_to_resume_ref(
        self, workdir: Path, data_dir: Path
    ) -> None:
        other = "22222222-2222-2222-2222-222222222222"
        await _run(_runtime(data_dir, Clients([_result(0.5)])), _ctx(workdir))

        # E.g. a forked session: its cumulative continues from the resumed transcript.
        forked = await _run(
            _runtime(data_dir, Clients([_result(0.8, session_id=other)])),
            _ctx(workdir, resume_ref=SESSION),
        )
        again = await _run(
            _runtime(data_dir, Clients([_result(0.9, session_id=other)])),
            _ctx(workdir, resume_ref=other),
        )

        assert _costs(forked) == [(pytest.approx(0.3), False)]
        assert _costs(again) == [(pytest.approx(0.1), False)]


class TestRegister:
    def test_register_claude(self, tmp_path: Path) -> None:
        factory = RuntimeFactory()
        register_claude(factory, Settings(data_dir=tmp_path / "data"))

        assert factory.has("claude")
        assert isinstance(factory.create("claude"), ClaudeRuntime)
