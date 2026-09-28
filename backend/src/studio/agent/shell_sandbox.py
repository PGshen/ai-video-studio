"""OpenAI 路径 Shell 的 macOS Seatbelt 沙箱（M1x T9，TD-20，ADR 0009）。

`LocalShellExecutor` 的每条命令都经 `/usr/bin/sandbox-exec -p <profile> /bin/sh -c <cmd>`
运行。配置在 `(allow default)` 之上收紧三件事：

- **写**：`(deny file-write*)` 后只放回当前工作区、专用临时目录
  （`<workdir>/.cache/tmp`，`TMPDIR` 指向它）、`/dev/null`、`/dev/tty`、`/dev/fd`
  （`/dev/stdout`、`/dev/stderr` 经它解析）；
- **读**：`(deny file-read*)` 仓库根与 `data_dir`，再放回当前工作区——与 Claude 路径的
  `claude_scope.sandbox_settings`（denyRead/allowRead）同一策略；
- **网络**：`(deny network*)`，包括本机回环；另外拒绝 mach-lookup 联系
  `com.apple.coreservices.launchservicesd`、拒绝发送 Apple Event、拒绝 exec
  `/usr/bin/open`/`/usr/bin/osascript`——否则 `(allow default)` 下 `lsappinfo
  front`/`open <url>`/`osascript -e '...'` 能经 LaunchServices 或 Apple Event
  间接指使沙箱外的进程（比如默认浏览器）联网，绕开上面的 `(deny network*)`
  （review 发现，详见 ADR 0009「影响」节）。

Seatbelt 同一操作后写的规则优先，所以"先拒父目录、后放回子目录"成立
（2026-09-28 本机 Darwin 24.6 实测，见 docs/references/openai-agents-sdk.md）。
路径一律取真实路径（macOS `/var` → `/private/var`），Seatbelt 按解析后的路径匹配。

`sandbox-exec` 只在 macOS 上存在（Apple 已标为 deprecated，但仍可用）；其他平台
`sandbox_available()` 为假，运行时不提供 Shell（失败关闭）。
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")

_WRITABLE_DEVICES = ('(literal "/dev/null")', '(literal "/dev/tty")', '(subpath "/dev/fd")')


def sandbox_available(platform: str | None = None, sandbox_exec: Path = SANDBOX_EXEC) -> bool:
    """本机能否用 `sandbox-exec` 包裹 Shell：必须是 macOS 且二进制存在。"""
    platform = sys.platform if platform is None else platform
    return platform == "darwin" and sandbox_exec.is_file()


def sandbox_tmpdir(workdir: Path) -> Path:
    """沙箱内 `TMPDIR`：工作区的 `.cache/tmp`（`.cache/` 不参与快照、不对前端列出）。"""
    return workdir / ".cache" / "tmp"


def _quote(path: Path) -> str:
    """SBPL 字符串字面量：转义反斜杠和双引号。"""
    escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _subpaths(paths: Sequence[Path]) -> str:
    return " ".join(f"(subpath {_quote(path)})" for path in paths)


def seatbelt_profile(workdir: Path, deny_read: Sequence[Path]) -> str:
    """生成本轮 Shell 的 Seatbelt 配置（SBPL）。`deny_read` 通常是 `[仓库根, data_dir]`。"""
    work = workdir.resolve()
    rules = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        # `(allow default)` 下 mach IPC 默认放行：`lsappinfo front`/`open`/
        # `osascript` 能经 mach-lookup 联系 launchservicesd、把 URL 交给未被
        # 沙箱管住的默认浏览器打开，或发送 Apple Event，绕开上面的
        # `(deny network*)`（review 发现，ADR 0009 残余风险节）。
        '(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd"))',
        "(deny appleevent-send)",
        '(deny process-exec (literal "/usr/bin/open") (literal "/usr/bin/osascript"))',
    ]
    if deny_read:
        rules.append(f"(deny file-read* {_subpaths([path.resolve() for path in deny_read])})")
    # Later rules win in Seatbelt: re-allow the workspace after denying its ancestors.
    rules.append(f"(allow file-read* {_subpaths([work])})")
    rules.append("(deny file-write*)")
    writable = " ".join([_subpaths([work, sandbox_tmpdir(work)]), *_WRITABLE_DEVICES])
    rules.append(f"(allow file-write* {writable})")
    return "\n".join(rules) + "\n"
