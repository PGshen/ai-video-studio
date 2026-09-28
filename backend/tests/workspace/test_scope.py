from __future__ import annotations

from pathlib import Path

from studio.workspace.blobs import BlobStore
from studio.workspace.scope import GuardReport, WriteScope, guard, is_writable


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


class TestIsWritable:
    def test_glob_star_star_matches_everything_under_dir(self) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])

        assert is_writable(scope, "topic/brief.md") is True
        assert is_writable(scope, "topic/notes/a.md") is True
        assert is_writable(scope, "style/STYLE.md") is False

    def test_exact_match(self) -> None:
        scope = WriteScope(writable=["narrative/narrative.json"], tool_managed=[])

        assert is_writable(scope, "narrative/narrative.json") is True
        assert is_writable(scope, "narrative/timing.json") is False

    def test_tool_managed_always_not_writable_even_if_matches_writable(self) -> None:
        scope = WriteScope(writable=["narrative/**"], tool_managed=["narrative/timing.json"])

        assert is_writable(scope, "narrative/narrative.json") is True
        assert is_writable(scope, "narrative/timing.json") is False


class TestGuard:
    def test_out_of_scope_addition_is_deleted(self, blobs: BlobStore, workdir: Path) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        before = {}
        _write(workdir / "style" / "STYLE.md", "hacked")
        after = {"style/STYLE.md": "whatever-sha-not-checked"}

        report = guard(workdir, before, after, scope, blobs, tool_writes={})

        assert not (workdir / "style" / "STYLE.md").exists()
        assert report.restored == ["style/STYLE.md"]

    def test_out_of_scope_modification_is_restored(self, blobs: BlobStore, workdir: Path) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        original_sha = blobs.put(b"original content")
        _write(workdir / "style" / "STYLE.md", "original content")
        before = {"style/STYLE.md": original_sha}
        _write(workdir / "style" / "STYLE.md", "tampered content")
        after = {"style/STYLE.md": blobs.put(b"tampered content")}

        report = guard(workdir, before, after, scope, blobs, tool_writes={})

        assert (workdir / "style" / "STYLE.md").read_text(encoding="utf-8") == "original content"
        assert report.restored == ["style/STYLE.md"]

    def test_out_of_scope_deletion_is_restored(self, blobs: BlobStore, workdir: Path) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        original_sha = blobs.put(b"original content")
        _write(workdir / "style" / "STYLE.md", "original content")
        before = {"style/STYLE.md": original_sha}
        (workdir / "style" / "STYLE.md").unlink()
        after = {}

        report = guard(workdir, before, after, scope, blobs, tool_writes={})

        assert (workdir / "style" / "STYLE.md").read_text(encoding="utf-8") == "original content"
        assert report.restored == ["style/STYLE.md"]

    def test_in_scope_changes_are_left_alone(self, blobs: BlobStore, workdir: Path) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        before = {}
        _write(workdir / "topic" / "brief.md", "draft")
        after = {"topic/brief.md": blobs.put(b"draft")}

        report = guard(workdir, before, after, scope, blobs, tool_writes={})

        assert (workdir / "topic" / "brief.md").read_text(encoding="utf-8") == "draft"
        assert report.restored == []

    def test_tool_managed_file_rewritten_by_agent_is_restored_to_tool_version(
        self, blobs: BlobStore, workdir: Path
    ) -> None:
        scope = WriteScope(writable=["narrative/**"], tool_managed=["narrative/timing.json"])
        tool_sha = blobs.put(b'{"tool": "version"}')
        _write(workdir / "narrative" / "timing.json", '{"tool": "version"}')
        before = {"narrative/timing.json": tool_sha}
        _write(workdir / "narrative" / "timing.json", '{"agent": "tampered"}')
        after = {"narrative/timing.json": blobs.put(b'{"agent": "tampered"}')}

        report = guard(
            workdir,
            before,
            after,
            scope,
            blobs,
            tool_writes={"narrative/timing.json": tool_sha},
        )

        content = (workdir / "narrative" / "timing.json").read_text(encoding="utf-8")
        assert content == '{"tool": "version"}'
        assert report.restored == ["narrative/timing.json"]

    def test_tool_write_matching_after_is_left_alone(self, blobs: BlobStore, workdir: Path) -> None:
        scope = WriteScope(writable=["narrative/**"], tool_managed=["narrative/timing.json"])
        tool_sha = blobs.put(b'{"tool": "version"}')
        _write(workdir / "narrative" / "timing.json", '{"tool": "version"}')
        before = {}
        after = {"narrative/timing.json": tool_sha}

        report = guard(
            workdir,
            before,
            after,
            scope,
            blobs,
            tool_writes={"narrative/timing.json": tool_sha},
        )

        assert report.restored == []

    def test_tool_managed_file_created_then_deleted_within_turn_is_restored(
        self, blobs: BlobStore, workdir: Path
    ) -> None:
        """工具本轮新建了托管文件，agent 又通过 Shell 把它删了：本轮开始和
        结束时该文件都不存在（before={}, after={}），但 `tool_writes` 里有
        记录，说明工具本轮确实写过——必须恢复为工具写入的内容，而不能因为
        `path` 不在 `before`/`after` 的并集里就被漏过。
        """
        scope = WriteScope(writable=["narrative/**"], tool_managed=["narrative/timing.json"])
        tool_sha = blobs.put(b'{"tool": "version"}')
        before: dict[str, str] = {}
        after: dict[str, str] = {}

        report = guard(
            workdir,
            before,
            after,
            scope,
            blobs,
            tool_writes={"narrative/timing.json": tool_sha},
        )

        content = (workdir / "narrative" / "timing.json").read_text(encoding="utf-8")
        assert content == '{"tool": "version"}'
        assert report.restored == ["narrative/timing.json"]

    def test_deletes_symlinks_outside_excluded_dirs(self, blobs: BlobStore, workdir: Path) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        _write(workdir / "topic" / "brief.md", "draft")
        (workdir / "topic" / "escape.md").symlink_to("/etc/passwd")
        (workdir / "linked_dir").symlink_to(workdir / "topic")

        report = guard(workdir, {}, {}, scope, blobs, tool_writes={})

        assert not (workdir / "topic" / "escape.md").exists()
        assert not (workdir / "linked_dir").exists()
        assert set(report.restored) == {"topic/escape.md", "linked_dir"}

    def test_symlink_inside_excluded_dir_is_left_alone(
        self, blobs: BlobStore, workdir: Path
    ) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        (workdir / "upstream" / "topic").mkdir(parents=True)
        _write(workdir / "topic" / "brief.md", "draft")
        (workdir / "output").mkdir()
        (workdir / "output" / "link.mp4").symlink_to("/dev/null")

        report = guard(workdir, {}, {}, scope, blobs, tool_writes={})

        assert (workdir / "output" / "link.mp4").is_symlink()
        assert report.restored == []

    def test_restore_does_not_write_through_symlinked_directory(
        self, blobs: BlobStore, workdir: Path, tmp_path: Path
    ) -> None:
        # Agent: `rm -rf style && ln -s <external> style`.
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        original_sha = blobs.put(b"# style")
        before = {"style/STYLE.md": original_sha}
        external = tmp_path / "external"
        external.mkdir()
        (workdir / "style").symlink_to(external, target_is_directory=True)
        after: dict[str, str] = {}

        report = guard(workdir, before, after, scope, blobs, tool_writes={})

        assert list(external.iterdir()) == []
        assert not (workdir / "style").is_symlink()
        assert (workdir / "style" / "STYLE.md").read_bytes() == b"# style"
        assert "style/STYLE.md" in report.restored

    def test_prunes_empty_dirs_left_by_removed_out_of_scope_file(
        self, blobs: BlobStore, workdir: Path
    ) -> None:
        """TD-5：越界新建的 `a/b/c.txt` 被还原（删除）后，`a/`、`a/b/` 这两个
        因此变空的目录也要清掉，不能留在工作区里。"""
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        before: dict[str, str] = {}
        _write(workdir / "a" / "b" / "c.txt", "escaped")
        after = {"a/b/c.txt": "whatever-sha-not-checked"}

        guard(workdir, before, after, scope, blobs, tool_writes={})

        assert not (workdir / "a").exists()

    def test_unrelated_preexisting_empty_dir_is_left_alone_when_nothing_restored_there(
        self, blobs: BlobStore, workdir: Path
    ) -> None:
        """`guard` 只应该清理它自己制造的空目录（还原/删除越界文件后留下的），
        不能把工作区里其他原因产生的空目录（比如 agent 刚 `mkdir -p` 出来、
        这一轮还没来得及写文件）也顺手删掉——那不是它的还原结果。"""
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        (workdir / "animation" / "assets").mkdir(parents=True)
        before: dict[str, str] = {}
        _write(workdir / "a" / "b" / "escaped.txt", "escaped")
        after = {"a/b/escaped.txt": "whatever-sha-not-checked"}

        guard(workdir, before, after, scope, blobs, tool_writes={})

        assert not (workdir / "a").exists()
        assert (workdir / "animation" / "assets").is_dir()

    def test_restore_replaces_directory_created_at_file_path(
        self, blobs: BlobStore, workdir: Path
    ) -> None:
        scope = WriteScope(writable=["topic/**"], tool_managed=[])
        original_sha = blobs.put(b"# style")
        before = {"style/STYLE.md": original_sha}
        (workdir / "style" / "STYLE.md").mkdir(parents=True)

        report = guard(workdir, before, {}, scope, blobs, tool_writes={})

        assert (workdir / "style" / "STYLE.md").read_bytes() == b"# style"
        assert report.restored == ["style/STYLE.md"]


def test_guard_report_is_dataclass() -> None:
    report = GuardReport(restored=["a"])
    assert report.restored == ["a"]
