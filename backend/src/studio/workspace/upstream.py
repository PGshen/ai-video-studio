"""上游只读副本（设计 §4.3、§4.4）。

每轮开始前，TurnRunner 把上游各阶段定稿快照的产物目录物化到工作区的
`upstream/<stage>/`，供当前阶段的原生文件工具直接读取。`upstream/` 是排除
目录（`EXCLUDED_TOP_DIRS`），不参与快照，每轮都从定稿快照重建，agent 对它的
任何改动都不会保留。
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from studio.workspace.blobs import BlobStore
from studio.workspace.snapshot import Manifest

_READONLY_FILE_MODE = 0o444


def _make_tree_writable(path: Path) -> None:
    """回收只读权限，以便 `shutil.rmtree` 能删除上一轮物化的只读文件。

    跳过符号链接：`materialize_upstream` 本身不会写符号链接，但排除目录本来
    就不受越界检查约束，agent 仍可能在上一轮往 `upstream/<stage>/` 里放一个
    符号链接。`chmod` 默认跟随符号链接，会改到链接目标（可能在工作区之外）
    的权限；不跟随（`follow_symlinks=False`）在部分平台上 `chmod` 又不支持
    对符号链接本身生效，所以干脆跳过——`shutil.rmtree` 删除符号链接本身不
    需要先改它的权限。
    """
    for root, dirnames, filenames in os.walk(path):
        for name in (*dirnames, *filenames):
            entry = Path(root) / name
            if entry.is_symlink():
                continue
            try:
                entry.chmod(entry.stat().st_mode | stat.S_IWUSR)
            except FileNotFoundError:
                pass


def _clear_dir(path: Path) -> None:
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
