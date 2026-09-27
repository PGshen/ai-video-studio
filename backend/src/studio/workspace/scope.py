"""写权限范围与事后越界防线（设计 §4.3）。

`WriteScope` 由各阶段定义声明（M1 是占位定义），描述该阶段允许 agent 直接写入
的相对路径 glob；`tool_managed` 中的路径即使匹配 `writable` 也不能由 agent
直接写，只能由工具生成（例如 `narrative/timing.json`）。

`guard` 是设计 §4.3 的「事后兜底」防线：每轮结束、创建快照之前，对比本轮前后
的扫描结果，把落在可写范围之外的改动（包括通过 Shell 做的改动）还原为本轮
开始时的内容；工具托管文件以本轮工具最后一次写入的内容为准。它还会清除
agent 在可快照目录里留下的符号链接——`scan()` 会忽略符号链接，如果不在这里
清理，agent 创建的符号链接会一直留在工作区里，可能被用来绕过越界检查。
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path

from studio.workspace.blobs import BlobStore
from studio.workspace.layout import EXCLUDED_TOP_DIRS
from studio.workspace.snapshot import Manifest


@dataclass(frozen=True, slots=True)
class WriteScope:
    """一个阶段的可写范围声明（相对工作区的 POSIX glob）。"""

    writable: list[str]
    tool_managed: list[str]
    """工具托管文件：即使匹配 `writable`，agent 也不能直接写。"""


def _matches_any(patterns: list[str], relpath: str) -> bool:
    return any(fnmatch.fnmatchcase(relpath, pattern) for pattern in patterns)


def is_writable(scope: WriteScope, relpath: str) -> bool:
    """`relpath`（POSIX 相对路径）是否在 `scope` 允许 agent 直接写入的范围内。

    用 `fnmatch` 做 glob 匹配：`*` 匹配任意字符（含 `/`），所以 `topic/**`
    能匹配 `topic/` 下任意深度的文件；没有通配符的模式则要求完全相等。
    """
    if _matches_any(scope.tool_managed, relpath):
        return False
    return _matches_any(scope.writable, relpath)


@dataclass(frozen=True, slots=True)
class GuardReport:
    """一轮越界检查的结果。"""

    restored: list[str]
    """被还原（含新增被删除、修改/删除被恢复）或被清除的符号链接的相对路径。"""


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _find_symlinks(workdir: Path) -> list[Path]:
    """找出工作区里排除目录之外的所有符号链接（文件或目录）。"""
    symlinks: list[Path] = []
    for root, dirnames, filenames in os.walk(workdir, followlinks=False):
        root_path = Path(root)
        if root_path == workdir:
            dirnames[:] = [name for name in dirnames if name not in EXCLUDED_TOP_DIRS]

        kept_dirnames = []
        for dirname in dirnames:
            dir_path = root_path / dirname
            if dir_path.is_symlink():
                symlinks.append(dir_path)
            else:
                kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames

        for filename in filenames:
            file_path = root_path / filename
            if file_path.is_symlink():
                symlinks.append(file_path)

    return symlinks


def guard(
    workdir: Path | str,
    before: Manifest,
    after: Manifest,
    scope: WriteScope,
    blobs: BlobStore,
    tool_writes: dict[str, str],
) -> GuardReport:
    """事后兜底：还原越界改动，并清除排除目录之外遗留的符号链接。

    - `tool_writes` 中的路径以其记录的 sha256 为准，与本轮工具写入不一致就
      恢复为工具版本（对应文件的内容必须已经在 `blobs` 中）。
    - 其余路径：在可写范围内的改动保留；范围外的新增被删除，修改/删除的
      内容从 `before`（`blobs` 中对应的 sha256）恢复。
    - `upstream/` 等排除目录不参与 `scan()`，因此不会出现在 `before`/`after`
      里，天然不受这里的还原逻辑影响。
    """
    workdir = Path(workdir)
    restored: list[str] = []

    for path in sorted(set(before) | set(after)):
        if path in tool_writes:
            expected_sha256 = tool_writes[path]
            if after.get(path) != expected_sha256:
                _write_bytes(workdir / path, blobs.get(expected_sha256))
                restored.append(path)
            continue

        if is_writable(scope, path):
            continue

        before_sha256 = before.get(path)
        if before_sha256 == after.get(path):
            continue

        if before_sha256 is None:
            (workdir / path).unlink(missing_ok=True)
        else:
            _write_bytes(workdir / path, blobs.get(before_sha256))
        restored.append(path)

    for symlink_path in _find_symlinks(workdir):
        symlink_path.unlink()
        restored.append(symlink_path.relative_to(workdir).as_posix())

    return GuardReport(restored=sorted(restored))
