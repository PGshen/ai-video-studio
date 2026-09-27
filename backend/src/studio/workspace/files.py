"""受控的工作区文件读写（设计 §4.3）。

供 api（文件浏览/编辑接口）与兜底文件工具（OpenAI 运行时、`ApplyPatchEditor`）
使用。这是「事前拦截」的一环：写入前直接检查路径安全性和可写范围，越界时
拒绝而不是事后靠 `scope.guard` 补救；Shell 等原生工具做出的越界改动仍然要靠
`scope.guard` 在回合结束时兜底。
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from studio.workspace.layout import PathEscapesWorkdir, resolve_relpath
from studio.workspace.scope import WriteScope, is_writable


class ScopeError(Exception):
    """路径不安全（绝对路径、`..`、越出工作区、经过符号链接），或不在可写范围内。"""


def safe_path(workdir: Path | str, relpath: str) -> Path:
    """校验 `relpath` 合法且落在 `workdir` 内，返回绝对路径；否则抛出 `ScopeError`。

    拒绝：绝对路径、包含 `..`、空路径、路径中任一环节（含最终文件本身）是
    符号链接、解析后越出工作区。
    """
    workdir = Path(workdir)
    rel = PurePosixPath(relpath)
    if rel.is_absolute() or not rel.parts:
        raise ScopeError(f"路径不合法：{relpath}")
    if ".." in rel.parts:
        raise ScopeError(f"路径不能包含 ..：{relpath}")

    current = workdir
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ScopeError(f"路径经过符号链接：{relpath}")

    try:
        return resolve_relpath(workdir, relpath)
    except PathEscapesWorkdir as exc:
        raise ScopeError(f"路径越出工作区：{relpath}") from exc


def list_tree(workdir: Path | str) -> list[str]:
    """列出工作区内所有普通文件的相对路径（POSIX 风格，按字典序排序）。

    跳过符号链接（文件或目录）；工作区不存在时返回空列表。
    """
    workdir = Path(workdir)
    if not workdir.is_dir():
        return []

    paths: list[str] = []
    for root, dirnames, filenames in os.walk(workdir, followlinks=False):
        root_path = Path(root)
        dirnames[:] = [name for name in dirnames if not (root_path / name).is_symlink()]

        for filename in filenames:
            file_path = root_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            paths.append(file_path.relative_to(workdir).as_posix())

    return sorted(paths)


def read_text(workdir: Path | str, relpath: str) -> str:
    """按相对路径读取文本内容（UTF-8）；路径不安全时抛出 `ScopeError`。"""
    path = safe_path(workdir, relpath)
    return path.read_text(encoding="utf-8")


def write_text(workdir: Path | str, relpath: str, content: str, scope: WriteScope) -> None:
    """在可写范围内写入文本（UTF-8），自动创建父目录。

    路径不安全或不在 `scope` 允许 agent 写入的范围内时抛出 `ScopeError`。
    """
    path = safe_path(workdir, relpath)
    if not is_writable(scope, relpath):
        raise ScopeError(f"不在可写范围内：{relpath}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_text_unscoped(workdir: Path | str, relpath: str, content: str) -> None:
    """写入文本（UTF-8），不检查可写范围（T5 决策记录：模拟 Shell 等绕过
    事前拦截的原生工具——真实的 Shell 能写工作区内任意路径，不会经过这里
    的任何检查；这个函数只是测试场景下"合法工作区路径、越界可写范围"这种
    写入的最小实现，仍然复用 `safe_path` 拒绝路径遍历和符号链接，避免测试
    代码本身把文件写出工作区）。

    路径不安全（绝对路径、`..`、经过符号链接、越出工作区）时抛出
    `ScopeError`；不检查 `WriteScope`。
    """
    path = safe_path(workdir, relpath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
