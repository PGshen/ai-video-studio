"""内容寻址的 blob 存储（设计 §3.3）。

以内容的 sha256 十六进制摘要为文件名，写入前先写临时文件再原子 `rename`，
避免进程中途退出留下半截文件；内容已存在时直接跳过写入。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


class BlobStore:
    """`<root>/<sha256>` 形式的内容寻址存储。"""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, sha256: str) -> Path:
        return self.root / sha256

    def put(self, data: bytes) -> str:
        """写入内容，返回其 sha256；内容已存在时跳过写入。"""
        sha256 = hashlib.sha256(data).hexdigest()
        dest = self._path_for(sha256)
        if dest.exists():
            return sha256

        fd, tmp_path_str = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "wb") as tmp_file:
                tmp_file.write(data)
            os.replace(tmp_path, dest)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        return sha256

    def get(self, sha256: str) -> bytes:
        """按 sha256 读取内容；不存在时抛出 `FileNotFoundError`。"""
        return self._path_for(sha256).read_bytes()

    def exists(self, sha256: str) -> bool:
        return self._path_for(sha256).exists()
