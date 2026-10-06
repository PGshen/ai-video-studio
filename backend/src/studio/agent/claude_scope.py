"""Claude 原生工具的读写范围（从 `claude_runtime` 拆出，见其模块文档的"权限"一节）。

`PreToolUse` hook 拒绝写到可写范围之外的 Write/Edit/MultiEdit/NotebookEdit、
拒绝读工作区之外的 Read/Glob/Grep；Bash 靠 SDK sandbox（`sandbox_settings`：
按本轮工作区生成，拒读仓库与数据目录）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Required, TypedDict

from claude_agent_sdk.types import (
    HookCallback,
    HookContext,
    HookInput,
    HookJSONOutput,
    SandboxSettings,
)

from studio.agent.sandbox_paths import sensitive_home_dirs
from studio.workspace.scope import WriteScope, is_writable

GUARDED_WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")

READ_TOOLS = ("Read", "Glob", "Grep")
"""受读取范围 hook 约束的原生只读工具：路径必须落在工作区内（含 `upstream/`）。"""


class SandboxFilesystem(TypedDict):
    """CLI 的 `sandbox.filesystem` 中本项目用到的部分（SDK 的 `SandboxSettings` 没有
    声明这个字段；CLI 另有 `allowWrite`/`denyWrite`）。"""

    denyRead: list[str]
    allowRead: list[str]


class StudioSandboxSettings(SandboxSettings, total=False):
    """`SandboxSettings` 加上 `filesystem`。SDK 把 `options.sandbox` 原样合并进 `--settings`
    的 JSON（`subprocess_cli.py: _build_settings_value`），多出的键会带给 CLI。"""

    filesystem: Required[SandboxFilesystem]


def sandbox_settings(
    workdir: Path, repo_root: Path, data_dir: Path, *, home: Path | None = None
) -> StudioSandboxSettings:
    """本轮的 Bash sandbox（TD-1）：拒读仓库、数据目录和主目录下的凭据目录
    （`sandbox_paths.sensitive_home_dirs`，TD-27），再放回当前工作区。

    CLI 的 `allowRead` 优先于 `denyRead`（2026-09-28 实测，见
    docs/references/claude-agent-sdk.md），所以拒读父目录后能放回其下的工作区；
    其他项目的工作区、`studio.db`、`backend/.env` 仍读不到。路径全部解析成真实路径
    （macOS 的 `/var` → `/private/var` 之类）。R3（T15 实测）：工作区外写入、外网都被拦住。
    """
    return {
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        # Without this the model can opt out per command via dangerouslyDisableSandbox.
        "allowUnsandboxedCommands": False,
        "filesystem": {
            "denyRead": [
                str(repo_root.resolve()),
                str(data_dir.resolve()),
                *(str(path) for path in sensitive_home_dirs(home)),
            ],
            "allowRead": [str(workdir.resolve())],
        },
    }


_PADDING = "\ufeff"
"""JS `String.prototype.trim()` also strips U+FEFF, which Python's `str.strip()` keeps."""


def _padded(raw: str) -> bool:
    """首尾带空白（含 U+FEFF）的路径/模式一律拒绝。

    内置 CLI 的 `expandPath` 先 `trim()` 再展开 `~`、解析相对路径，而 hook 按原串判断：
    `" /etc/passwd"` 在 hook 看来是工作区内的相对路径，CLI 实际读的却是 `/etc/passwd`。
    直接拒绝比模仿 CLI 的 trim 规则更稳妥，正常的工具调用不会带这样的路径。
    """
    return raw != raw.strip() or raw.strip(_PADDING) != raw


def write_denial_reason(workdir: Path, scope: WriteScope, tool_input: dict[str, Any]) -> str | None:
    """Write/Edit 类工具的目标不在 `scope` 内时返回拒绝原因，否则 `None`。"""
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    allowed = "、".join(scope.writable) or "（无）"
    if not isinstance(raw, str) or not raw:
        return f"无法确定写入目标路径，已拒绝。本阶段可写：{allowed}"
    if _padded(raw):
        return f"路径 {raw!r} 首尾带空白，已拒绝。本阶段可写：{allowed}"
    if raw.startswith("~"):
        return f"{raw} 在项目工作区之外，已拒绝。本阶段可写：{allowed}"
    target = Path(raw)
    if not target.is_absolute():
        target = workdir / target
    try:
        relpath = target.resolve().relative_to(workdir).as_posix()
    except ValueError:
        return f"{raw} 在项目工作区之外，已拒绝。本阶段可写：{allowed}"
    if not is_writable(scope, relpath):
        return f"{relpath} 不在本阶段可写范围内，已拒绝。本阶段可写：{allowed}"
    return None


def _escapes(workdir: Path, raw: str) -> bool:
    """`raw`（相对 `workdir` 或绝对路径）解析符号链接和 `..` 之后是否落在 `workdir` 外。

    以 `~` 开头的一律算越界（F1）：内置 CLI 的 `expandPath` 会把 `~`、`~/…` 展开成家目录，
    而 `Path` 把它当普通相对段。`~user/…` CLI 不展开（按工作区内的相对路径处理），
    这里同样拒绝，免得依赖这一细节。首尾带空白的也算越界（见 `_padded`）。
    """
    if _padded(raw) or raw.startswith("~"):
        return True
    target = Path(raw)
    if not target.is_absolute():
        target = workdir / target
    resolved = target.resolve()
    return resolved != workdir and workdir not in resolved.parents


MAX_READ_IMAGE_BYTES = 300_000
"""Largest image/PDF the built-in `Read` may open. The CLI writes a result's base64 twice per
transcript line, so a larger file can push one line past the SDK message buffer."""
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}


def _too_big_to_read(workdir: Path, raw: str) -> bool:
    target = Path(raw)
    if not target.is_absolute():
        target = workdir / target
    try:
        return (
            target.suffix.lower() in _IMAGE_SUFFIXES
            and target.stat().st_size > MAX_READ_IMAGE_BYTES
        )
    except OSError:
        return False


def read_denial_reason(workdir: Path, tool_name: str, tool_input: dict[str, Any]) -> str | None:
    """Read/Glob/Grep 的目标不在工作区内时返回拒绝原因，否则 `None`（I5）。

    - Read：`file_path` 必填，解析后必须在工作区内；
    - Glob/Grep：`path` 缺省即工作区（cwd），给了就必须在工作区内；glob 模式
      （Glob 的 `pattern`、Grep 的 `glob`）不能是绝对路径、以 `~` 开头、含 `..` 或首尾带空白。
    """
    refuse = "只能读取项目工作区内的文件，已拒绝：{}"
    if tool_name == "Read":
        raw = tool_input.get("file_path")
        if not isinstance(raw, str) or not raw:
            return refuse.format("无法确定读取路径")
        if _escapes(workdir, raw):
            return refuse.format(raw)
        if _too_big_to_read(workdir, raw):
            return (
                f"{raw} 超过 {MAX_READ_IMAGE_BYTES // 1000} kB，不能用 Read 读（会撑爆缓冲区）。"
                "请看工具返回的附图（render_preview_html、analyze_music、render_music）。"
            )
        return None

    raw_path = tool_input.get("path")
    if raw_path is not None and (not isinstance(raw_path, str) or _escapes(workdir, raw_path)):
        return refuse.format(raw_path)
    pattern = tool_input.get("pattern" if tool_name == "Glob" else "glob")
    if isinstance(pattern, str) and (
        _padded(pattern) or pattern.startswith(("/", "~")) or ".." in Path(pattern).parts
    ):
        return refuse.format(pattern)
    return None


def read_scope_hook(workdir: Path) -> HookCallback:
    async def hook(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}
        reason = read_denial_reason(workdir, input_data["tool_name"], input_data["tool_input"])
        if reason is None:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return hook


def write_scope_hook(workdir: Path, scope: WriteScope) -> HookCallback:
    async def hook(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}
        reason = write_denial_reason(workdir, scope, input_data["tool_input"])
        if reason is None:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return hook
