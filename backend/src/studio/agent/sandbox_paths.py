"""两条沙箱路径（Claude Bash、OpenAI Shell）共用的拒读清单里“主目录敏感位置”的部分（TD-27）。

仓库根和 `data_dir` 由各运行时自己传入；这里只补主目录下几处存放凭据的目录，
免得提示注入让 agent 用 `cat ~/.ssh/id_*` 之类把内容经工具结果带出来。
`~/.claude/projects`（登录模式下所有 studio 项目的会话 transcript）不在这里：拒读它可能
影响 Claude CLI 自己的会话记账，需要真机验证后再决定（仍登记在 TD-27）。
"""

from __future__ import annotations

from pathlib import Path

_SENSITIVE_HOME_SUBDIRS = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".docker",
    "Library/Keychains",
)


def sensitive_home_dirs(home: Path | None = None) -> list[Path]:
    """`home` 下存放密钥/凭据的目录（不要求存在）。"""
    base = (home if home is not None else Path.home()).resolve()
    return [base / sub for sub in _SENSITIVE_HOME_SUBDIRS]
