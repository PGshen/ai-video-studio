"""codex 执行命令的隔离：permission profile（codex-runtime T5；实测见 codex.md「沙箱与读隔离」）。

用 `-c` 定义一个继承 `:workspace` 的 profile：拒读仓库根、数据目录和主目录下的凭据目录
（`sandbox_paths`，含 ChatGPT 登录所在的 `~/.codex`），再把本轮工作区放回为可写；
`:tmpdir`、`:slash_tmp` 改为只读。更具体的路径优先，所以"拒读父目录、放回子目录"成立，与 Claude
路径的 `denyRead` + `allowRead` 同一策略。内置 `:workspace` 默认断网。profile 只约束模型执行的
命令，不约束 codex 自己（MCP 连接、读图片附件）。`sandbox_mode`（`-s`）与 `default_permissions`
互斥，所以有 profile 时不传 `-s`。
"""

from __future__ import annotations

from pathlib import Path

from studio.agent.codex_args import toml_string
from studio.agent.exec_policy import ExecMode
from studio.agent.sandbox_paths import sensitive_home_dirs

PROFILE_NAME = "studio"


def permission_args(
    workdir: Path, repo_root: Path, data_dir: Path, *, home: Path | None = None
) -> list[str]:
    entries: dict[str, str] = {}
    for denied in (repo_root.resolve(), data_dir.resolve(), *sensitive_home_dirs(home)):
        entries[str(denied)] = "deny"
    entries[str(workdir.resolve())] = "write"  # last: wins over a denied root at the same path
    entries[":tmpdir"] = "read"
    entries[":slash_tmp"] = "read"
    table = ", ".join(
        f"{toml_string(path)}={toml_string(level)}" for path, level in entries.items()
    )
    prefix = f"permissions.{PROFILE_NAME}."
    return [
        "-c",
        f"{prefix}extends={toml_string(':workspace')}",
        "-c",
        f"{prefix}filesystem={{{table}}}",
        "-c",
        f"default_permissions={toml_string(PROFILE_NAME)}",
    ]


def sandbox_args(
    mode: ExecMode, workdir: Path, repo_root: Path, data_dir: Path, *, home: Path | None = None
) -> list[str] | None:
    """按 `exec_policy.exec_mode` 的结果给参数；`disabled` 返回 `None`（本轮不能执行命令）。"""
    if mode == "sandboxed":
        return permission_args(workdir, repo_root, data_dir, home=home)
    if mode == "unsandboxed":
        return ["-s", "danger-full-access"]
    return None
