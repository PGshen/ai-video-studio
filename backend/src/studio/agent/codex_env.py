"""codex 子进程的环境变量（codex-runtime T3，ADR 0030「认证」）。

codex 用本机 ChatGPT 登录（`$CODEX_HOME/auth.json`，默认 `~/.codex/`）。继承来的环境里有
`CODEX_API_KEY` 时它会覆盖登录、改走 API key 计费（codex.md 实测），所以先去掉一切 OpenAI/
Codex/Anthropic/本应用前缀的变量和名字像密钥的变量——这些值也不该经模型执行的命令被读到。
`CODEX_HOME` 例外：它决定去哪里读登录，原样保留（不设就是默认位置）。
"""

from __future__ import annotations

from collections.abc import Mapping

from studio import proc

_DROPPED_PREFIXES = ("OPENAI_", "CODEX_", "AZURE_OPENAI", "ANTHROPIC_", "CLAUDE_CODE_", "STUDIO_")
_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
_KEPT = frozenset({"CODEX_HOME"})


def build_env(environ: Mapping[str, str], *, platform: str | None = None) -> dict[str, str]:
    """继承环境去掉认证覆盖与密钥类变量之后的副本（调用方再加本轮 MCP 令牌）。"""
    kept = {
        key: value
        for key, value in environ.items()
        if key in _KEPT
        or (
            not key.upper().startswith(_DROPPED_PREFIXES)
            and not any(marker in key.upper() for marker in _SECRET_MARKERS)
        )
    }
    return proc.child_env(kept, platform=platform, environ=environ)
