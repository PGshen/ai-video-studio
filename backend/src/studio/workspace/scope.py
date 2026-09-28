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
import shutil
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


def _clear_obstacle(path: Path) -> None:
    """删掉挡在还原路径上的东西：符号链接或文件只 unlink（不跟随），目录整棵删除。"""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _restore_bytes(workdir: Path, relpath: str, data: bytes) -> None:
    """把 `data` 写回 `workdir/relpath`，保证写入不经过任何符号链接。

    guard 已先清除了可快照目录里的符号链接，这里再逐级检查一次（防御性）：
    路径中间任一环节是符号链接或普通文件就删掉它再建目录；目标本身是符号
    链接或目录也先删掉，避免写穿到工作区外或因 `IsADirectoryError` 卡住。
    """
    parts = Path(relpath).parts
    current = workdir
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            current.unlink()
        if not current.exists():
            current.mkdir()
    dest = current / parts[-1]
    if dest.is_symlink() or dest.is_dir():
        _clear_obstacle(dest)
    dest.write_bytes(data)


def _remove_file(workdir: Path, relpath: str) -> None:
    """删除一个越界新增的文件；路径上有符号链接时不跟随（符号链接已由 guard 清除）。"""
    current = workdir
    for part in Path(relpath).parts:
        current = current / part
        if current.is_symlink():
            return
    if current.is_file():
        current.unlink()


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


def _prune_empty_ancestors(workdir: Path, restored: list[str]) -> None:
    """只清理这一轮真的被还原/删除的路径留下的空祖先目录，不扫整棵树。

    与全量的 `layout.prune_empty_dirs` 不同：不会碰到跟本轮还原无关、agent
    这一轮刚 `mkdir -p` 出来但还没写文件的空目录（review 发现）。
    """
    seen_dirs: set[Path] = set()
    for relpath in restored:
        parent = (workdir / relpath).parent
        while parent != workdir and parent not in seen_dirs:
            seen_dirs.add(parent)
            rel_parts = parent.relative_to(workdir).parts
            if rel_parts and rel_parts[0] in EXCLUDED_TOP_DIRS:
                break
            try:
                next(parent.iterdir())
                break  # 非空，停止往上清
            except FileNotFoundError:
                parent = parent.parent
                continue
            except StopIteration:
                pass
            parent.rmdir()
            parent = parent.parent


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

    # Symlinks first: a restore must never write through a directory symlink the
    # agent planted (e.g. `rm -rf style && ln -s /outside style`).
    for symlink_path in _find_symlinks(workdir):
        symlink_path.unlink()
        restored.append(symlink_path.relative_to(workdir).as_posix())

    for path in sorted(set(before) | set(after) | set(tool_writes)):
        if path in tool_writes:
            expected_sha256 = tool_writes[path]
            if after.get(path) != expected_sha256:
                _restore_bytes(workdir, path, blobs.get(expected_sha256))
                restored.append(path)
            continue

        if is_writable(scope, path):
            continue

        before_sha256 = before.get(path)
        if before_sha256 == after.get(path):
            continue

        if before_sha256 is None:
            _remove_file(workdir, path)
        else:
            _restore_bytes(workdir, path, blobs.get(before_sha256))
        restored.append(path)

    # 还原/删除越界文件后，父目录可能变空（例如越界新建的 `a/b/c.txt` 被删掉
    # 后留下空的 `a/`、`a/b/`）；和 `snapshot.rollback` 一样清理掉（TD-5）。
    # 只清理这一轮实际还原路径的祖先目录，不扫整棵工作区树，避免碰到跟本轮
    # 还原无关的空目录（review 发现）。
    _prune_empty_ancestors(workdir, restored)

    return GuardReport(restored=sorted(set(restored)))
