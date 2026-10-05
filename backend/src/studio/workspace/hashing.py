"""文件内容哈希，按 (mtime, size) 缓存：预览与配乐元数据在每次工作区变化后都会重新取，
几十 MB 的 wav 不该每次都整读一遍算 sha256。缓存只在进程内、有上限；
同一纳秒内同大小地改写同一个文件会命中旧值，对本项目（人或 agent 手动保存、渲染产物）可忽略。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

MAX_ENTRIES = 64
_CHUNK = 1024 * 1024
_cache: dict[str, tuple[int, int, str]] = {}


def file_sha256(path: Path) -> str:
    """`path` 内容的 sha256（十六进制）；文件不存在抛 `FileNotFoundError`。"""
    stat = path.stat()
    key = str(path)
    hit = _cache.get(key)
    if hit is not None and hit[0] == stat.st_mtime_ns and hit[1] == stat.st_size:
        return hit[2]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    if len(_cache) >= MAX_ENTRIES and key not in _cache:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (stat.st_mtime_ns, stat.st_size, digest.hexdigest())
    return digest.hexdigest()
