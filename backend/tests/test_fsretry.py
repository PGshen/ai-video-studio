"""`studio.fsretry`: renames and deletes that wait briefly for another reader (design §12, P12).

On Windows a file another process has open cannot be replaced or deleted (WinError 5 / 32);
the API streaming `final.mp4` while a re-render finishes is the typical case.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from studio import fsretry


class _Flaky:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise PermissionError(13, "in use")
        return "done"


def test_retries_permission_errors_on_windows() -> None:
    flaky = _Flaky(3)
    sleeps: list[float] = []
    assert fsretry.retrying(flaky, platform="win32", sleep=sleeps.append) == "done"
    assert flaky.calls == 4 and len(sleeps) == 3


def test_gives_up_after_about_a_second() -> None:
    flaky = _Flaky(10_000)
    sleeps: list[float] = []
    with pytest.raises(PermissionError):
        fsretry.retrying(flaky, platform="win32", sleep=sleeps.append)
    assert 0.8 <= sum(sleeps) <= 1.5


def test_posix_does_not_wait_for_a_real_permission_problem() -> None:
    flaky = _Flaky(1)
    with pytest.raises(PermissionError):
        fsretry.retrying(flaky, platform="darwin", sleep=lambda _s: None)
    assert flaky.calls == 1


def test_other_errors_are_not_retried() -> None:
    def missing() -> None:
        raise FileNotFoundError("gone")

    with pytest.raises(FileNotFoundError):
        fsretry.retrying(missing, platform="win32", sleep=lambda _s: None)


def _hold_open(path: Path, seconds: float) -> threading.Thread:
    handle = path.open("rb")
    timer = threading.Timer(seconds, handle.close)
    timer.start()
    return timer


def test_replace_waits_for_a_reader_to_close(tmp_path: Path) -> None:
    dst, tmp = tmp_path / "final.mp4", tmp_path / "final.tmp.mp4"
    dst.write_bytes(b"old")
    tmp.write_bytes(b"new")
    reader = _hold_open(dst, 0.3)
    fsretry.replace(tmp, dst)
    reader.join()
    assert dst.read_bytes() == b"new" and not tmp.exists()


def test_unlink_waits_for_a_reader_to_close(tmp_path: Path) -> None:
    path = tmp_path / "music.wav"
    path.write_bytes(b"x")
    reader = _hold_open(path, 0.3)
    fsretry.unlink(path)
    reader.join()
    assert not path.exists()
    fsretry.unlink(path, missing_ok=True)


def test_rmtree_waits_for_a_reader_to_close(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    (folder / "sub").mkdir(parents=True)
    held = folder / "sub" / "a.wav"
    held.write_bytes(b"x")
    reader = _hold_open(held, 0.3)
    fsretry.rmtree(folder)
    reader.join()
    assert not folder.exists()
