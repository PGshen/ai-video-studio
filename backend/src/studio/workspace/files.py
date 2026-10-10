"""受控的工作区文件读写（设计 §4.3）。

供 api（文件浏览/编辑接口）与兜底文件工具（OpenAI 运行时、`ApplyPatchEditor`）
使用。这是「事前拦截」的一环：写入前直接检查路径安全性和可写范围，越界时
拒绝而不是事后靠 `scope.guard` 补救；Shell 等原生工具做出的越界改动仍然要靠
`scope.guard` 在回合结束时兜底。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath

from studio import fsretry
from studio.workspace.layout import (
    HIDDEN_TOP_DIRS,
    PathEscapesWorkdir,
    project_dir,
    resolve_relpath,
    scratch_dir,
)
from studio.workspace.scope import WriteScope, is_writable


class ScopeError(Exception):
    """路径不安全（绝对路径、`..`、越出工作区、经过符号链接），或不在可写范围内。"""


# Device names Windows resolves in any directory, with or without an extension.
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{dev}{n}" for dev in ("COM", "LPT") for n in [*"0123456789", "¹", "²", "³"]}
)


def check_model_path(relpath: str) -> PurePosixPath:
    """校验并规范化模型给出的工作区相对路径（设计 §5），两个平台用同一套规则。

    拒绝：空路径；含反斜杠（统一用 `/`）、`:`（盘符、NTFS 备用数据流）或 NUL；以 `/` 开头
    或按 Windows 规则带盘符/根；任何一段是 `..`；任何一段以空格或 `.` 结尾（Windows 会
    悄悄去掉，变成另一个文件）；任何一段是 Windows 保留设备名（`CON`、`aux.txt`……）。
    `.` 段和重复的 `/` 被去掉（`narrative/./timing.json` → `narrative/timing.json`）。
    """
    if not relpath or "\0" in relpath:
        raise ScopeError(f"路径不合法：{relpath!r}")
    if "\\" in relpath:
        raise ScopeError(f"路径只能用 / 分隔：{relpath}")
    if ":" in relpath:
        raise ScopeError(f"路径不能包含冒号：{relpath}")
    windows = PureWindowsPath(relpath)
    rel = PurePosixPath(relpath)
    if rel.is_absolute() or windows.drive or windows.root or not rel.parts:
        raise ScopeError(f"路径不合法：{relpath}")
    for part in rel.parts:
        if part == "..":
            raise ScopeError(f"路径不能包含 ..：{relpath}")
        if part.endswith((" ", ".")):
            raise ScopeError(f"路径的每一段不能以空格或 . 结尾：{relpath}")
        if part.split(".", 1)[0].rstrip(" ").upper() in _WINDOWS_RESERVED:
            raise ScopeError(f"路径里有 Windows 保留的设备名：{relpath}")
    return rel


def relpath_within(workdir: Path | str, raw: str) -> str:
    """模型给出的路径（相对路径，或 Claude 工具给的绝对路径）→ 工作区相对路径。

    相对路径先过 `check_model_path`（`.` 表示工作区本身）；然后解析符号链接和 `..`，
    确认结果在工作区内，按 `os.path.normcase` 比较（NTFS 不区分大小写）。工作区本身返回
    `""`；越界或不合法时抛出 `ScopeError`。读写 hook 和 `apply_patch` 共用这一个判断。
    """
    root = Path(workdir).resolve()
    target = Path(raw)
    if not target.is_absolute():
        target = root if raw in (".", "./") else root / check_model_path(raw)
    resolved = target.resolve()
    root_key = os.path.normcase(str(root))
    key = os.path.normcase(str(resolved))
    if key == root_key:
        return ""
    prefix = root_key.rstrip(os.sep) + os.sep
    if not key.startswith(prefix):
        raise ScopeError(f"{raw} 在项目工作区之外")
    relpath = Path(str(resolved)[len(prefix) :]).as_posix()
    check_model_path(relpath)
    return relpath


def _is_hidden_top_dir(relpath: str) -> bool:
    """`relpath` 的顶层目录是否在 `HIDDEN_TOP_DIRS` 里（`.cache/`、`output/`）。"""
    top = PurePosixPath(relpath).parts[0]
    return top in HIDDEN_TOP_DIRS


def normalize_relpath(relpath: str) -> str:
    """规范化工作区相对路径：去掉 `.` 段和重复的 `/`（`narrative/./timing.json` →
    `narrative/timing.json`）；空路径、绝对路径、含 `..` 时抛出 `ScopeError`。

    写入/删除前的范围检查必须用规范化后的路径，否则 `narrative//timing.json`
    这类写法能绕过 `tool_managed` 的 glob 匹配（`safe_path` 仍会解析到同一个文件）。
    """
    return check_model_path(relpath).as_posix()


def safe_path(workdir: Path | str, relpath: str) -> Path:
    """校验 `relpath` 合法且落在 `workdir` 内，返回绝对路径；否则抛出 `ScopeError`。

    拒绝：绝对路径、包含 `..`、空路径、路径中任一环节（含最终文件本身）是
    符号链接、解析后越出工作区。
    """
    workdir = Path(workdir)
    rel = check_model_path(relpath)

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

    跳过符号链接（文件或目录）、跳过 `HIDDEN_TOP_DIRS`（`.cache/`、`output/`，
    TD-5：这两个目录不是"工作区内容"，调用方不应该看到）；`upstream/` 仍然
    列出。工作区不存在时返回空列表。
    """
    workdir = Path(workdir)
    if not workdir.is_dir():
        return []

    paths: list[str] = []
    for root, dirnames, filenames in os.walk(workdir, followlinks=False):
        root_path = Path(root)
        if root_path == workdir:
            dirnames[:] = [name for name in dirnames if name not in HIDDEN_TOP_DIRS]
        dirnames[:] = [name for name in dirnames if not (root_path / name).is_symlink()]

        for filename in filenames:
            file_path = root_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            paths.append(file_path.relative_to(workdir).as_posix())

    return sorted(paths)


def read_bytes(workdir: Path | str, relpath: str) -> bytes:
    """按相对路径读取原始字节；路径不安全时抛出 `ScopeError`。

    TurnRunner 用它把工具托管文件（工具刚写入的内容）存进 blob 库，供
    `scope.guard` 在轮末按工具写入的版本恢复。
    """
    return safe_path(workdir, relpath).read_bytes()


def read_text(workdir: Path | str, relpath: str) -> str:
    """按相对路径读取文本内容（UTF-8）。

    路径不安全，或落在 `HIDDEN_TOP_DIRS`（`.cache/`、`output/`）之下时抛出
    `ScopeError`（TD-5）；`upstream/` 不受影响，仍然可读。
    """
    path = safe_path(workdir, relpath)
    if _is_hidden_top_dir(relpath):
        raise ScopeError(f"路径不可读：{relpath}")
    return path.read_text(encoding="utf-8")


def write_text(workdir: Path | str, relpath: str, content: str, scope: WriteScope) -> None:
    """在可写范围内写入文本（UTF-8），自动创建父目录。

    路径不安全或不在 `scope` 允许 agent 写入的范围内时抛出 `ScopeError`。
    """
    relpath = normalize_relpath(relpath)
    path = safe_path(workdir, relpath)
    if not is_writable(scope, relpath):
        raise ScopeError(f"不在可写范围内：{relpath}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def delete_file(workdir: Path | str, relpath: str, scope: WriteScope) -> None:
    """在可写范围内删除一个普通文件（`ApplyPatchEditor.delete_file` 使用）。

    路径不安全或不在 `scope` 内时抛出 `ScopeError`；文件不存在抛出
    `FileNotFoundError`；目标是目录抛出 `IsADirectoryError`。
    """
    relpath = normalize_relpath(relpath)
    path = safe_path(workdir, relpath)
    if not is_writable(scope, relpath):
        raise ScopeError(f"不在可写范围内：{relpath}")
    if path.is_dir():
        raise IsADirectoryError(f"是目录，不能删除：{relpath}")
    fsretry.unlink(path)


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
    path.write_text(content, encoding="utf-8", newline="")


def init_workspace(data_dir: Path | str, project_id: str, initial_files: dict[str, str]) -> Path:
    """创建项目工作区并写入初始文本文件（例如 `style/STYLE.md` 占位），返回工作区目录。

    不检查可写范围（建项目时由 api 决定写什么），但仍用 `safe_path` 拒绝不安全路径。
    """
    workdir = project_dir(data_dir, project_id)
    workdir.mkdir(parents=True, exist_ok=True)
    for relpath, content in initial_files.items():
        write_text_unscoped(workdir, relpath, content)
    return workdir


def reset_scratch(data_dir: Path | str, session_id: str) -> Path:
    """把无项目会话的 scratch 目录重置为空目录并返回它（每轮开始前调用）。"""
    path = scratch_dir(data_dir, session_id)
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def remove_scratch(data_dir: Path | str, session_id: str | None = None) -> None:
    """删除无项目会话的 scratch 目录；`session_id` 为空时删除全部（进程启动时清理遗留）。"""
    path = scratch_dir(data_dir, session_id) if session_id else Path(data_dir) / "scratch"
    shutil.rmtree(path, ignore_errors=True)


def remove_workspace(data_dir: Path | str, project_id: str) -> None:
    """删除整个项目工作区（建项目失败时清理用）；目录不存在时什么都不做。"""
    shutil.rmtree(project_dir(data_dir, project_id), ignore_errors=True)
