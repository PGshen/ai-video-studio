"""Model-supplied paths are checked by one platform-independent rule set (design §5).

Every case here must hold on macOS and on Windows: a path that is harmless on one platform
can name a different file (or a device) on the other.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from studio.workspace import files
from studio.workspace.files import ScopeError, check_model_path, relpath_within

MALICIOUS = [
    "",
    "/etc/passwd",
    "//server/share/x",
    "notes\\..\\..\\x",
    "notes\\x.md",
    "C:/x",
    "C:\\x",
    "c:x",
    "\\\\?\\C:\\x",
    "\\\\server\\share\\x",
    "a/b:stream",
    "notes.md:$DATA",
    "CON",
    "CON.txt",
    "con.tar.gz",
    "aux",
    "notes/nul.md",
    "COM1",
    "lpt9.log",
    "dir./x",
    "notes/x.",
    "x ",
    "notes/x /y",
    "..",
    "../x",
    "notes/../../x",
    "notes/..",
    "...",
    ".",
    "./",
    "a\x00b",
]

LEGAL = {
    "narrative/./timing.json": "narrative/timing.json",
    "./topic//a.md": "topic/a.md",
    "topic/brief.md": "topic/brief.md",
    ".cache/x.json": ".cache/x.json",
    "scenes/01-intro.html": "scenes/01-intro.html",
    "uploads/1a2b3c4d-报告 v2.pdf": "uploads/1a2b3c4d-报告 v2.pdf",
    "music/compose.py": "music/compose.py",
    "console.md": "console.md",
    "auxiliary/nullable.md": "auxiliary/nullable.md",
    "COM10.txt": "COM10.txt",
    "a.b.c": "a.b.c",
}


@pytest.mark.parametrize("raw", MALICIOUS)
def test_malicious_paths_are_rejected(raw: str) -> None:
    with pytest.raises(ScopeError):
        check_model_path(raw)


@pytest.mark.parametrize("raw", MALICIOUS)
def test_normalize_and_safe_path_share_the_rules(raw: str, tmp_path: Path) -> None:
    with pytest.raises(ScopeError):
        files.normalize_relpath(raw)
    with pytest.raises(ScopeError):
        files.safe_path(tmp_path, raw)


@pytest.mark.parametrize(("raw", "normalized"), LEGAL.items())
def test_legal_paths_pass_and_are_normalized(raw: str, normalized: str) -> None:
    assert check_model_path(raw) == PurePosixPath(normalized)
    assert files.normalize_relpath(raw) == normalized


def test_the_error_names_the_original_path() -> None:
    with pytest.raises(ScopeError, match="CON.txt"):
        check_model_path("notes/CON.txt")


# ---- relpath_within: absolute paths the Claude tools give, and relative ones ----


def test_absolute_path_inside_the_workspace(tmp_path: Path) -> None:
    (tmp_path / "topic").mkdir()
    assert relpath_within(tmp_path, str(tmp_path / "topic" / "a.md")) == "topic/a.md"


def test_relative_path_is_checked_and_resolved(tmp_path: Path) -> None:
    assert relpath_within(tmp_path, "./topic//a.md") == "topic/a.md"
    assert relpath_within(tmp_path, ".") == ""
    assert relpath_within(tmp_path, str(tmp_path)) == ""


@pytest.mark.parametrize("raw", ["notes\\x.md", "C:x", "a/b:s", "CON.txt", "../x", "x."])
def test_relative_model_path_rules_apply(raw: str, tmp_path: Path) -> None:
    with pytest.raises(ScopeError):
        relpath_within(tmp_path, raw)


def test_absolute_path_outside_is_rejected(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(ScopeError, match="工作区之外"):
        relpath_within(work, str(tmp_path / "other" / "a.md"))
    with pytest.raises(ScopeError, match="工作区之外"):
        relpath_within(work, str(tmp_path / "work-sibling" / "a.md"))


def test_windows_style_absolute_path_is_rejected_wherever_it_is_not_absolute(
    tmp_path: Path,
) -> None:
    """On macOS `C:\\...` is a relative name; on Windows it is absolute and outside."""
    raw = str(PureWindowsPath("C:/Windows/System32/drivers/etc/hosts"))
    with pytest.raises(ScopeError):
        relpath_within(tmp_path, raw)


def test_symlink_escaping_the_workspace_is_rejected(
    tmp_path: Path, symlinks_supported: None
) -> None:
    work = tmp_path / "work"
    outside = tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    (work / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ScopeError):
        relpath_within(work, "link/secret.md")


@pytest.mark.skipif(os.name != "nt", reason="NTFS 不区分大小写；POSIX 上大小写不同就是不同的路径")
def test_windows_compares_case_insensitively(tmp_path: Path) -> None:
    (tmp_path / "topic").mkdir()
    upper = str(tmp_path).upper() + "\\topic\\a.md"
    assert relpath_within(tmp_path, upper) == "topic/a.md"
