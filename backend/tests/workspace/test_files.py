from __future__ import annotations

from pathlib import Path

import pytest

from studio.workspace.files import (
    ScopeError,
    delete_file,
    init_workspace,
    list_tree,
    normalize_relpath,
    read_bytes,
    read_text,
    remove_workspace,
    safe_path,
    write_text,
    write_text_unscoped,
)
from studio.workspace.scope import WriteScope


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


class TestSafePath:
    def test_rejects_absolute_path(self, workdir: Path) -> None:
        with pytest.raises(ScopeError):
            safe_path(workdir, "/etc/passwd")

    def test_rejects_dotdot(self, workdir: Path) -> None:
        with pytest.raises(ScopeError):
            safe_path(workdir, "../outside.md")

    def test_rejects_dotdot_in_the_middle(self, workdir: Path) -> None:
        with pytest.raises(ScopeError):
            safe_path(workdir, "topic/../../outside.md")

    def test_rejects_path_that_escapes_workdir_after_resolution(
        self, workdir: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (workdir / "escape").symlink_to(outside)

        with pytest.raises(ScopeError):
            safe_path(workdir, "escape/file.md")

    def test_rejects_symlink_as_final_component(self, workdir: Path, tmp_path: Path) -> None:
        target = tmp_path / "secret.txt"
        target.write_text("secret", encoding="utf-8")
        (workdir / "link.md").symlink_to(target)

        with pytest.raises(ScopeError):
            safe_path(workdir, "link.md")

    def test_accepts_plain_relative_path(self, workdir: Path) -> None:
        result = safe_path(workdir, "topic/brief.md")

        assert result == workdir / "topic" / "brief.md"

    def test_rejects_empty_path(self, workdir: Path) -> None:
        with pytest.raises(ScopeError):
            safe_path(workdir, "")


class TestListTree:
    def test_lists_files_skips_symlinks(self, workdir: Path) -> None:
        _write(workdir / "topic" / "brief.md", "hello")
        _write(workdir / "style" / "STYLE.md", "style")
        (workdir / "topic" / "link.md").symlink_to(workdir / "topic" / "brief.md")

        result = list_tree(workdir)

        assert result == ["style/STYLE.md", "topic/brief.md"]

    def test_missing_workdir_returns_empty(self, tmp_path: Path) -> None:
        assert list_tree(tmp_path / "does-not-exist") == []


class TestReadText:
    def test_reads_existing_file(self, workdir: Path) -> None:
        _write(workdir / "topic" / "brief.md", "hello")

        assert read_text(workdir, "topic/brief.md") == "hello"

    def test_rejects_unsafe_path(self, workdir: Path) -> None:
        with pytest.raises(ScopeError):
            read_text(workdir, "../outside.md")


class TestWriteText:
    def test_writes_within_scope(self, workdir: Path) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])

        write_text(workdir, "topic/brief.md", "hello", scope)

        assert (workdir / "topic" / "brief.md").read_text(encoding="utf-8") == "hello"

    def test_creates_parent_directories(self, workdir: Path) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])

        write_text(workdir, "topic/notes/a.md", "note", scope)

        assert (workdir / "topic" / "notes" / "a.md").read_text(encoding="utf-8") == "note"

    def test_rejects_write_outside_scope(self, workdir: Path) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])

        with pytest.raises(ScopeError):
            write_text(workdir, "style/STYLE.md", "hacked", scope)

        assert not (workdir / "style" / "STYLE.md").exists()

    def test_rejects_write_to_tool_managed_file(self, workdir: Path) -> None:
        scope = WriteScope(writable=["narrative/**"], tool_managed=["narrative/timing.json"])

        with pytest.raises(ScopeError):
            write_text(workdir, "narrative/timing.json", "{}", scope)

    def test_rejects_unsafe_path_even_if_pattern_matches(self, workdir: Path) -> None:
        scope = WriteScope(writable=["**"], tool_managed=[])

        with pytest.raises(ScopeError):
            write_text(workdir, "../outside.md", "hacked", scope)


class TestWriteTextUnscoped:
    def test_writes_outside_any_scope(self, workdir: Path) -> None:
        write_text_unscoped(workdir, "style/STYLE.md", "hacked via shell")

        assert (workdir / "style" / "STYLE.md").read_text(encoding="utf-8") == "hacked via shell"

    def test_still_rejects_unsafe_path(self, workdir: Path) -> None:
        with pytest.raises(ScopeError):
            write_text_unscoped(workdir, "../outside.md", "hacked")


class TestReadBytes:
    def test_reads_raw_bytes(self, workdir: Path) -> None:
        _write(workdir / "narrative" / "timing.json", b"\x00\x01")

        assert read_bytes(workdir, "narrative/timing.json") == b"\x00\x01"

    def test_rejects_unsafe_path(self, workdir: Path) -> None:
        with pytest.raises(ScopeError):
            read_bytes(workdir, "../outside")


class TestDeleteFile:
    _SCOPE = WriteScope(writable=["topic/**"], tool_managed=["topic/managed.json"])

    def test_deletes_file_within_scope(self, workdir: Path) -> None:
        _write(workdir / "topic" / "a.md", "x")
        delete_file(workdir, "topic/a.md", self._SCOPE)
        assert not (workdir / "topic" / "a.md").exists()

    def test_rejects_delete_outside_scope(self, workdir: Path) -> None:
        _write(workdir / "style" / "STYLE.md", "x")
        with pytest.raises(ScopeError):
            delete_file(workdir, "style/STYLE.md", self._SCOPE)
        assert (workdir / "style" / "STYLE.md").exists()

    def test_rejects_delete_of_tool_managed_file(self, workdir: Path) -> None:
        _write(workdir / "topic" / "managed.json", "{}")
        with pytest.raises(ScopeError):
            delete_file(workdir, "topic/managed.json", self._SCOPE)

    def test_missing_file_raises_file_not_found(self, workdir: Path) -> None:
        with pytest.raises(FileNotFoundError):
            delete_file(workdir, "topic/missing.md", self._SCOPE)

    def test_rejects_directory(self, workdir: Path) -> None:
        (workdir / "topic" / "sub").mkdir(parents=True)
        with pytest.raises(IsADirectoryError):
            delete_file(workdir, "topic/sub", self._SCOPE)


class TestNormalizedScopeChecks:
    """Un-normalised spellings must not slip past the tool_managed check."""

    _SCOPE = WriteScope(writable=["narrative/**"], tool_managed=["narrative/timing.json"])

    @pytest.mark.parametrize(
        "relpath", ["narrative/./timing.json", "narrative//timing.json", "./narrative/timing.json"]
    )
    def test_write_to_managed_file_via_odd_spelling_is_rejected(
        self, workdir: Path, relpath: str
    ) -> None:
        with pytest.raises(ScopeError):
            write_text(workdir, relpath, "{}", self._SCOPE)
        assert not (workdir / "narrative" / "timing.json").exists()

    def test_delete_managed_file_via_odd_spelling_is_rejected(self, workdir: Path) -> None:
        _write(workdir / "narrative" / "timing.json", "{}")
        with pytest.raises(ScopeError):
            delete_file(workdir, "narrative/./timing.json", self._SCOPE)
        assert (workdir / "narrative" / "timing.json").exists()

    def test_normalize_relpath(self) -> None:
        assert normalize_relpath("narrative/./a//b.json") == "narrative/a/b.json"
        assert normalize_relpath("./topic/a.md") == "topic/a.md"
        for bad in ("", ".", "/etc/passwd", "topic/../x"):
            with pytest.raises(ScopeError):
                normalize_relpath(bad)


class TestInitAndRemoveWorkspace:
    def test_init_creates_workdir_with_initial_files(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"

        workdir = init_workspace(data_dir, "p1", {"style/STYLE.md": "# style\n"})

        assert workdir == data_dir / "projects" / "p1"
        assert (workdir / "style" / "STYLE.md").read_text(encoding="utf-8") == "# style\n"

    def test_init_rejects_unsafe_paths(self, tmp_path: Path) -> None:
        with pytest.raises(ScopeError):
            init_workspace(tmp_path / "data", "p1", {"../escape.md": "x"})

    def test_remove_deletes_workdir_and_tolerates_missing(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        workdir = init_workspace(data_dir, "p1", {"style/STYLE.md": "x"})

        remove_workspace(data_dir, "p1")
        remove_workspace(data_dir, "p1")

        assert not workdir.exists()
