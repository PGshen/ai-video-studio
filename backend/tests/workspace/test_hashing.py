"""`workspace.hashing.file_sha256`：按 (mtime, size) 缓存的文件哈希（3B 评审遗留）。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from studio.workspace import hashing
from studio.workspace.hashing import file_sha256


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_matches_hashlib_for_small_and_large_files(tmp_path: Path) -> None:
    small, large = tmp_path / "a.bin", tmp_path / "b.bin"
    small.write_bytes(b"hello")
    large.write_bytes(os.urandom(3 * 1024 * 1024 + 17))
    assert file_sha256(small) == _sha(b"hello")
    assert file_sha256(large) == _sha(large.read_bytes())
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    assert file_sha256(empty) == _sha(b"")


def test_an_unchanged_file_is_not_read_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"x" * 1000)
    first = file_sha256(path)
    reads: list[Path] = []
    real_open = Path.open

    def spy(self: Path, *args: Any, **kwargs: Any) -> Any:
        reads.append(self)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy)
    assert file_sha256(path) == first
    assert reads == []


def test_a_changed_file_is_hashed_again(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"one")
    assert file_sha256(path) == _sha(b"one")
    path.write_bytes(b"three")  # size changed
    assert file_sha256(path) == _sha(b"three")
    path.write_bytes(b"THREE")  # same size, new mtime
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 5_000_000))
    assert file_sha256(path) == _sha(b"THREE")


def test_missing_file_raises_and_the_cache_stays_bounded(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        file_sha256(tmp_path / "nope")
    for index in range(hashing.MAX_ENTRIES + 20):
        path = tmp_path / f"f{index}"
        path.write_bytes(bytes([index % 256]))
        file_sha256(path)
    assert len(hashing._cache) <= hashing.MAX_ENTRIES
