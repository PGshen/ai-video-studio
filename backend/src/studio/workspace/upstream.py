"""上游只读副本（设计 §4.3、§4.4）。

每轮开始前，TurnRunner 把上游各阶段定稿快照的产物目录物化到工作区的
`upstream/<stage>/`，供当前阶段的原生文件工具直接读取。`upstream/` 是排除
目录（`EXCLUDED_TOP_DIRS`），不参与快照，每轮都从定稿快照重建，agent 对它的
任何改动都不会保留。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path

from studio.workspace.blobs import BlobStore
from studio.workspace.snapshot import Manifest

_READONLY_FILE_MODE = 0o444


def _make_tree_writable(path: Path) -> None:
    """回收权限，以便 `shutil.rmtree` 能删除上一轮物化的只读文件。

    目录补上 `u+rwx`（agent 可能 `chmod 000 upstream/topic`，没有 r/x 就
    列不出、删不掉里面的条目），文件补上 `u+w`。自顶向下遍历，先改父目录
    的权限再进入它。跳过符号链接：`chmod` 默认跟随符号链接，会改到链接目标
    （可能在工作区之外）的权限；`shutil.rmtree` 删除符号链接本身不需要改它
    的权限。
    """
    path.chmod(path.stat().st_mode | stat.S_IRWXU)
    for root, dirnames, filenames in os.walk(path):
        root_path = Path(root)
        for name in dirnames:
            entry = root_path / name
            if entry.is_symlink():
                continue
            try:
                entry.chmod(entry.stat().st_mode | stat.S_IRWXU)
            except FileNotFoundError:
                pass
        for name in filenames:
            entry = root_path / name
            if entry.is_symlink():
                continue
            try:
                entry.chmod(entry.stat().st_mode | stat.S_IWUSR)
            except FileNotFoundError:
                pass


def _clear_dir(path: Path) -> None:
    """删除 `path`：符号链接或文件只 unlink（不跟随、不改链接目标权限），目录整棵删除。"""
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if not path.exists():
        return
    _make_tree_writable(path)
    shutil.rmtree(path)


def materialize_upstream(
    workdir: Path | str,
    blobs: BlobStore,
    sources: dict[str, Manifest | None],
) -> None:
    """清空并重建 `upstream/<stage>/`。

    `sources` 是 `{阶段名: 该阶段定稿快照的清单 | None}`；`None` 表示该阶段
    尚无定稿，对应的 `upstream/<stage>/` 就不创建。只复制清单中属于该阶段
    产物目录（路径以 `<stage>/` 开头）的文件，其余路径（例如 `style/`）跳过。
    物化出的文件设为只读，防止 agent 误以为可以直接修改。
    """
    workdir = Path(workdir)
    upstream_root = workdir / "upstream"
    _clear_dir(upstream_root)

    for stage, manifest in sources.items():
        if manifest is None:
            continue

        prefix = f"{stage}/"
        for rel_path, sha256 in manifest.items():
            if not rel_path.startswith(prefix):
                continue

            dest = upstream_root / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blobs.get(sha256))
            dest.chmod(_READONLY_FILE_MODE)


def _expected_upstream(sources: dict[str, Manifest | None]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for stage, manifest in sources.items():
        for rel_path, sha256 in (manifest or {}).items():
            if rel_path.startswith(f"{stage}/"):
                expected[f"upstream/{rel_path}"] = sha256
    return expected


def upstream_drift(workdir: Path | str, sources: dict[str, Manifest | None]) -> list[str]:
    """`upstream/` 当前内容与按 `sources` 物化的结果不同的路径（`upstream/...`，排序）。

    TurnRunner 在轮末重新物化之前调用，把 agent 对只读副本的改动（新增、修改、
    删除、符号链接）报告为"被还原"，写进下一轮前言（R5、评审关注点 1）。
    符号链接不跟随，一律视为改动。
    """
    workdir = Path(workdir)
    expected = _expected_upstream(sources)
    actual: dict[str, str] = {}
    if (workdir / "upstream").is_symlink():
        # os.walk would follow a symlinked top directory; report it instead.
        return sorted({"upstream", *expected})
    for root, dirnames, filenames in os.walk(workdir / "upstream", followlinks=False):
        root_path = Path(root)
        for name in (*dirnames, *filenames):
            entry = root_path / name
            rel_path = entry.relative_to(workdir).as_posix()
            if entry.is_symlink():
                actual[rel_path] = "symlink"
            elif entry.is_file():
                try:
                    actual[rel_path] = hashlib.sha256(entry.read_bytes()).hexdigest()
                except OSError:
                    # Unreadable (e.g. agent ran `chmod 000`): count it as drift.
                    actual[rel_path] = "unreadable"
    return sorted(
        path for path in set(expected) | set(actual) if expected.get(path) != actual.get(path)
    )
