"""定位 `runtime=codex` 用的 Codex CLI（ADR 0030 前提 2，codex-runtime T1）。

用 ChatGPT 桌面版自带的 CLI（随桌面版自动更新的 alpha 版；负责人 2026-10-13 决定不另装固定版本：
另装同样约 340 MB，下载很慢）。版本漂移靠两处兜底：运行时把 codex 的配置警告记进日志并提示，
`make smoke` 的 codex 用例对比 `VERIFIED_VERSION`。`STUDIO_CODEX_BIN` 可以改用别的 CLI
（Windows 或想锁定版本时）。不搜 PATH：用户自己装的 codex 版本不受控。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from pathlib import Path

from studio import proc

VERIFIED_VERSION = "0.162.0-alpha.17.2"
"""docs/references/codex.md 实测所用的版本；冒烟发现版本不同时提醒复验。"""

_BUNDLED = Path("ChatGPT.app/Contents/Resources/codex-cli/bin/codex")
_VERSION_LINE = re.compile(r"^codex-cli (\S+)$", re.MULTILINE)
_VERSION_TIMEOUT_S = 15


class CodexVersionError(RuntimeError):
    """`codex --version` 失败或输出不认识。"""


def desktop_candidates(*, platform: str, home: Path | None = None) -> list[Path]:
    """ChatGPT 桌面版自带 CLI 的可能位置（只有 macOS 实测过）。"""
    if platform != "darwin":
        return []
    base = home if home is not None else Path.home()
    return [Path("/Applications") / _BUNDLED, base / "Applications" / _BUNDLED]


def find_codex(override: Path | None, candidates: Sequence[Path]) -> Path | None:
    """找到要用的 CLI；没有时返回 `None`（运行时不注册）。

    `override` 设了但文件不存在也返回 `None`，不回落到桌面版：写错的路径不能悄悄换成另一个 CLI。
    """
    if override is not None:
        return override if override.is_file() else None
    return next((path for path in candidates if path.is_file()), None)


async def codex_version(binary: Path) -> str:
    """`codex --version` 报告的版本号，例如 `0.162.0-alpha.17.2`。"""
    try:
        child = await asyncio.create_subprocess_exec(
            str(binary),
            "--version",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **proc.spawn_kwargs(),
        )
    except OSError as exc:
        raise CodexVersionError(f"无法运行 {binary} --version：{exc}") from exc
    try:
        out, _ = await asyncio.wait_for(child.communicate(), _VERSION_TIMEOUT_S)
    except TimeoutError as exc:
        await proc.kill_tree(child)
        raise CodexVersionError(f"{binary} --version 超时") from exc
    text = out.decode(errors="replace")
    match = _VERSION_LINE.search(text)
    if child.returncode != 0 or match is None:
        raise CodexVersionError(f"{binary} --version 的输出无法识别：{text.strip()[:200]}")
    return match.group(1)
