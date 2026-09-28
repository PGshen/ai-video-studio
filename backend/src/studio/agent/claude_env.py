"""Claude CLI 子进程的环境变量（从 `claude_runtime` 拆出，见其模块文档的"认证"一节）。

两种认证方式都先把父进程继承来的宿主变量和名字像密钥的变量置空，再按认证方式覆盖；
SDK 把 `env` 合并在 `os.environ` 之上，所以置空对 CLI 及其 Bash 子进程都生效。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from studio.agent import events

LOGIN_BLANKED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
"""登录模式下置空的环境变量：任一有值都会覆盖本机登录凭据。"""

DEFAULT_BASE_URL = "https://api.anthropic.com"
"""继承来的 `ANTHROPIC_BASE_URL` 被替换成的值（模型配置没设 `base_url` 时）。不置空：
CLI 里有 `process.env.X ?? process.env.ANTHROPIC_BASE_URL` 这样的写法，空串不算"未设置"。"""

HOST_BLANKED_ENV = frozenset(
    {
        # Credentials / auth routing a parent shell may carry.
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_PROFILE",
        "ANTHROPIC_UNIX_SOCKET",
        "ANTHROPIC_CUSTOM_HEADERS",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
        "CLAUDE_CODE_OAUTH_SCOPES",
        "CLAUDE_CODE_OAUTH_CLIENT_ID",
        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
        "CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR",
        "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST",
        # Model overrides (the profile's `model` must win).
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_FABLE_MODEL",
        "ANTHROPIC_SMALL_FAST_MODEL",
        # Provider switches (first-party API only in M1).
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_USE_GATEWAY",
        "CLAUDE_CODE_USE_MANTLE",
        "CLAUDE_CODE_USE_ANTHROPIC_AWS",
        "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
        # Host-integration markers set by Claude Code / the desktop app.
        "CLAUDE_CODE_EXECPATH",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING",
        "CLAUDE_CODE_EMIT_TOOL_USE_SUMMARIES",
        "CLAUDE_CODE_TERMINAL_MCP_TOOLS",
        "CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL",
        "CLAUDE_CODE_REPORT_FINDINGS",
        "CLAUDE_CODE_EAGER_FLUSH",
    }
)
"""父进程（例如在 Claude Code / Claude 桌面版里启动的 shell）可能带着、会改变认证方式、
模型、目标服务或宿主集成行为的变量；继承到的一律置空（CLI 按 JS 真值判断，空串即未设置）。
不动 `CLAUDE_CODE_ENTRYPOINT`（SDK 自己设 `sdk-py`）、`CLAUDE_CODE_SDK_READS_SESSION_STATE`
（SDK 只在键不存在时才设 `1`）、`CLAUDE_CONFIG_DIR`（登录模式靠它找到用户自己的登录凭据）。"""

HOST_BLANKED_PREFIXES = (
    "CLAUDE_CODE_HOST_",
    "CLAUDE_CODE_SDK_HAS_",
    "CLAUDE_CODE_MESSAGING_",
    "CLAUDE_CODE_SESSION_",
    "CLAUDE_CODE_REMOTE",
    "CLAUDE_CODE_DESKTOP_",
)
"""按前缀置空的宿主集成变量（宿主会话 id、消息 socket、宿主代管的 OAuth 刷新等）。"""

SECRET_NAME_RE = re.compile(r"(?:^|_)(?:API_?KEY|KEY|TOKEN|SECRET|PASSWORD|PASSWD)S?(?:_|$)")
"""名字像密钥的环境变量（按下划线分段匹配，大小写不敏感）：继承来的一律置空，
agent 的 Bash 就读不到其他服务的 key（例如 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY`），
再经 WebFetch 外发（I5）。按段匹配是为了不误伤 `SSH_AUTH_SOCK`、`KEYCHAIN_*` 之类。
当前配置用到的 `ANTHROPIC_API_KEY` 在 API key 模式下随后被重新写入。"""


class MissingApiKeyError(Exception):
    pass


def build_env(
    api_key_env: str | None,
    base_url: str | None,
    environ: Mapping[str, str],
    claude_dir: Path,
) -> tuple[events.AuthMode, dict[str, str]]:
    """返回认证方式和传给 CLI 子进程的 `env`（合并在 `os.environ` 之上）。

    继承来的宿主变量（`HOST_BLANKED_ENV`、`HOST_BLANKED_PREFIXES`）和名字像密钥的
    变量（`SECRET_NAME_RE`，含模型配置的 `api_key_env` 本身）先置空，
    `ANTHROPIC_BASE_URL` 换成模型配置的 `base_url` 或官方地址，再按认证方式覆盖。
    """
    env: dict[str, str] = {
        name: ""
        for name in environ
        if name in HOST_BLANKED_ENV
        or name.startswith(HOST_BLANKED_PREFIXES)
        or SECRET_NAME_RE.search(name.upper())
    }
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    elif "ANTHROPIC_BASE_URL" in environ:
        env["ANTHROPIC_BASE_URL"] = DEFAULT_BASE_URL
    if api_key_env is None:
        env.update(dict.fromkeys(LOGIN_BLANKED_ENV, ""))
        return "login", env
    key = environ.get(api_key_env)
    if not key:
        raise MissingApiKeyError(f"环境变量 {api_key_env} 未设置，无法调用 Claude（API key 模式）")
    env["ANTHROPIC_API_KEY"] = key
    env["ANTHROPIC_AUTH_TOKEN"] = ""
    env["CLAUDE_CONFIG_DIR"] = str(claude_dir)
    return "api_key", env
