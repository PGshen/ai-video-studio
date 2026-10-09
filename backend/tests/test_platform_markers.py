"""The platform markers in `conftest.py` (windows-native plan T8).

`posix_only` / `macos_only` / `windows_only` are the only way to skip a test by platform, and
each use must say why; these tests pin the decision function and the "reason required" rule.
"""

from __future__ import annotations

import pytest

from conftest import missing_symlink_privilege, platform_skip_reason


@pytest.mark.parametrize(
    ("marker", "platform", "skipped"),
    [
        ("posix_only", "win32", True),
        ("posix_only", "darwin", False),
        ("posix_only", "linux", False),
        ("macos_only", "win32", True),
        ("macos_only", "linux", True),
        ("macos_only", "darwin", False),
        ("windows_only", "darwin", True),
        ("windows_only", "win32", False),
    ],
)
def test_which_platforms_skip(marker: str, platform: str, skipped: bool) -> None:
    reason = platform_skip_reason(marker, "因为某个原因", platform)
    if skipped:
        assert reason is not None and "因为某个原因" in reason
    else:
        assert reason is None


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_reason_is_required(reason: str | None) -> None:
    with pytest.raises(pytest.UsageError, match="原因"):
        platform_skip_reason("posix_only", reason, "win32")


def test_unknown_markers_are_ignored() -> None:
    assert platform_skip_reason("slow", None, "win32") is None


class _WindowsError(OSError):
    """What Windows raises for a symlink without Developer Mode (ERROR_PRIVILEGE_NOT_HELD)."""

    winerror = 1314


def test_only_the_missing_symlink_privilege_is_recognised() -> None:
    assert missing_symlink_privilege(_WindowsError(22, "客户端没有所需的特权。"))
    assert not missing_symlink_privilege(OSError(2, "not found"))
    assert not missing_symlink_privilege(ValueError("x"))
