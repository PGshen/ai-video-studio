from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from studio.db.repo.snapshots import insert_snapshot, list_snapshots
from studio.workspace.blobs import BlobStore
from studio.workspace.layout import EXCLUDED_TOP_DIRS
from studio.workspace.snapshot import (
    create_snapshot,
    diff,
    read_file_at,
    rollback,
    scan,
)


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


class TestDataDirOf:
    def test_rejects_blob_store_root_not_named_blobs(
        self, engine: Engine, tmp_path: Path, project_id: str
    ) -> None:
        bad_blobs = BlobStore(tmp_path / "not-blobs")

        with pytest.raises(ValueError, match="blobs"):
            create_snapshot(engine, bad_blobs, project_id, reason="user_edit")


class TestScan:
    def test_excludes_top_level_excluded_dirs(self, workdir: Path) -> None:
        assert EXCLUDED_TOP_DIRS == {".cache", "output", "upstream"}
        _write(workdir / "topic" / "brief.md", "hello")
        _write(workdir / ".cache" / "tmp.txt", "cache")
        _write(workdir / "output" / "final.mp4", b"video")
        _write(workdir / "upstream" / "topic" / "brief.md", "upstream copy")

        manifest = scan(workdir)

        assert set(manifest) == {"topic/brief.md"}

    def test_ignores_symlinks(self, workdir: Path) -> None:
        _write(workdir / "topic" / "brief.md", "hello")
        (workdir / "topic" / "link.md").symlink_to(workdir / "topic" / "brief.md")
        (workdir / "linked_dir").symlink_to(workdir / "topic")

        manifest = scan(workdir)

        assert set(manifest) == {"topic/brief.md"}

    def test_uses_posix_relative_paths_and_sha256(self, workdir: Path) -> None:
        _write(workdir / "a" / "b.txt", "content")

        manifest = scan(workdir)

        assert "a/b.txt" in manifest
        assert len(manifest["a/b.txt"]) == 64

    def test_missing_workdir_returns_empty_manifest(self, tmp_path: Path) -> None:
        assert scan(tmp_path / "does-not-exist") == {}


class TestBlobStore:
    def test_put_is_content_addressed_and_dedups(self, tmp_path: Path) -> None:
        store = BlobStore(tmp_path / "blobs")

        sha1 = store.put(b"same content")
        sha2 = store.put(b"same content")

        assert sha1 == sha2
        files = [p for p in store.root.iterdir() if not p.name.startswith(".tmp-")]
        assert len(files) == 1

    def test_put_writes_atomically_no_leftover_temp_files(self, tmp_path: Path) -> None:
        store = BlobStore(tmp_path / "blobs")

        store.put(b"payload")

        leftover = list(store.root.glob(".tmp-*"))
        assert leftover == []

    def test_get_returns_stored_bytes(self, tmp_path: Path) -> None:
        store = BlobStore(tmp_path / "blobs")
        sha = store.put(b"payload")

        assert store.get(sha) == b"payload"

    def test_get_missing_raises(self, tmp_path: Path) -> None:
        store = BlobStore(tmp_path / "blobs")

        with pytest.raises(FileNotFoundError):
            store.get("0" * 64)


class TestCreateSnapshot:
    def test_creates_snapshot_from_scan(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "topic" / "brief.md", "v1")

        ref = create_snapshot(engine, blobs, project_id, reason="user_edit")

        assert ref.created is True
        assert ref.reason == "user_edit"
        assert ref.manifest == scan(workdir)
        assert read_file_at(blobs, ref.manifest, "topic/brief.md") == b"v1"

    def test_unchanged_manifest_returns_existing_snapshot(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "topic" / "brief.md", "v1")
        first = create_snapshot(engine, blobs, project_id, reason="user_edit")

        second = create_snapshot(engine, blobs, project_id, reason="turn")

        assert second.created is False
        assert second.id == first.id
        assert second.reason == first.reason

    def test_reads_each_file_at_most_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        engine: Engine,
        blobs: BlobStore,
        project_id: str,
        workdir: Path,
    ) -> None:
        """TD-4：`scan` 为算 sha256 读一遍文件，旧实现 `create_snapshot` 写 blob
        时又整个重读一遍——对已经在 blob 库里的内容（本例的 `a.md`/`b.md`）
        完全是浪费。改完之后不管 blob 是否已存在，每个文件在一轮里只读一次。
        """
        _write(workdir / "a.md", "same content")
        _write(workdir / "b.md", "other content")
        create_snapshot(engine, blobs, project_id, reason="user_edit")

        _write(workdir / "c.md", "new content")

        read_calls: list[Path] = []
        original_read_bytes = Path.read_bytes

        def counting_read_bytes(self: Path) -> bytes:
            read_calls.append(self)
            return original_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)

        create_snapshot(engine, blobs, project_id, reason="turn")

        assert len(read_calls) == 3


class TestDiff:
    def test_added_removed_modified(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "topic" / "a.md", "line1\nline2\n")
        _write(workdir / "topic" / "b.md", "keep me\n")
        old = create_snapshot(engine, blobs, project_id, reason="user_edit").manifest

        (workdir / "topic" / "a.md").unlink()
        _write(workdir / "topic" / "b.md", "keep me\nchanged\n")
        _write(workdir / "topic" / "c.md", "new file\n")
        new = create_snapshot(engine, blobs, project_id, reason="turn").manifest

        result = diff(old, new, blobs)

        assert result.added == ["topic/c.md"]
        assert result.removed == ["topic/a.md"]
        assert [m.path for m in result.modified] == ["topic/b.md"]
        modified = result.modified[0]
        assert modified.text_diff is not None
        assert "keep me" in modified.text_diff
        assert "+changed" in modified.text_diff

    def test_binary_modification_has_no_text_diff(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "asset.bin", b"\xff\xfe\x00\x01")
        old = create_snapshot(engine, blobs, project_id, reason="user_edit").manifest

        _write(workdir / "asset.bin", b"\xff\xfe\x00\x02")
        new = create_snapshot(engine, blobs, project_id, reason="turn").manifest

        result = diff(old, new, blobs)

        assert [m.path for m in result.modified] == ["asset.bin"]
        assert result.modified[0].text_diff is None


class TestReadFileAt:
    def test_reads_historical_content(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "topic" / "brief.md", "v1")
        snap = create_snapshot(engine, blobs, project_id, reason="user_edit")

        assert read_file_at(blobs, snap.manifest, "topic/brief.md") == b"v1"

    def test_missing_path_raises(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        snap = create_snapshot(engine, blobs, project_id, reason="user_edit")

        with pytest.raises(FileNotFoundError):
            read_file_at(blobs, snap.manifest, "missing.md")


class TestRollback:
    def test_restores_content_and_removes_extra_files(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "topic" / "a.md", "v1")
        snap1 = create_snapshot(engine, blobs, project_id, reason="user_edit")

        _write(workdir / "topic" / "a.md", "v2")
        _write(workdir / "topic" / "extra" / "nested.md", "extra")
        create_snapshot(engine, blobs, project_id, reason="turn")

        result = rollback(engine, blobs, project_id, snap1.id)

        assert result.created is True
        assert result.reason == "rollback"
        assert result.manifest == snap1.manifest
        assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "v1"
        assert not (workdir / "topic" / "extra").exists()

    def test_does_not_touch_excluded_dirs(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "topic" / "a.md", "v1")
        _write(workdir / ".cache" / "keep.txt", "cache")
        snap1 = create_snapshot(engine, blobs, project_id, reason="user_edit")

        _write(workdir / "topic" / "a.md", "v2")
        create_snapshot(engine, blobs, project_id, reason="turn")

        rollback(engine, blobs, project_id, snap1.id)

        assert (workdir / ".cache" / "keep.txt").read_text(encoding="utf-8") == "cache"

    def test_rollback_can_itself_be_rolled_back(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "topic" / "a.md", "v1")
        snap1 = create_snapshot(engine, blobs, project_id, reason="user_edit")

        _write(workdir / "topic" / "a.md", "v2")
        _write(workdir / "topic" / "b.md", "b content")
        snap2 = create_snapshot(engine, blobs, project_id, reason="turn")

        snap3 = rollback(engine, blobs, project_id, snap1.id)
        assert snap3.manifest == snap1.manifest
        assert not (workdir / "topic" / "b.md").exists()

        snap4 = rollback(engine, blobs, project_id, snap2.id)

        assert snap4.created is True
        assert snap4.manifest == snap2.manifest
        assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "v2"
        assert (workdir / "topic" / "b.md").read_text(encoding="utf-8") == "b content"

    def test_prunes_empty_directories(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "topic" / "a.md", "v1")
        snap1 = create_snapshot(engine, blobs, project_id, reason="user_edit")

        _write(workdir / "topic" / "sub" / "deep" / "nested.md", "nested")
        create_snapshot(engine, blobs, project_id, reason="turn")

        rollback(engine, blobs, project_id, snap1.id)

        assert not (workdir / "topic" / "sub").exists()
        assert (workdir / "topic").exists()

    def test_unknown_snapshot_id_raises(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        with pytest.raises(ValueError):
            rollback(engine, blobs, project_id, "does-not-exist")

    def test_unsnapshotted_manual_edit_is_recoverable_after_rollback(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "topic" / "a.md", "v1")
        snap1 = create_snapshot(engine, blobs, project_id, reason="turn")
        _write(workdir / "topic" / "a.md", "v2")
        create_snapshot(engine, blobs, project_id, reason="turn")

        # Manual edit that no snapshot has captured yet (PUT /files does not snapshot).
        _write(workdir / "topic" / "a.md", "manual")

        rollback(engine, blobs, project_id, snap1.id)
        assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "v1"

        edits = [
            snap
            for snap in list_snapshots(engine, project_id)
            if snap.manifest.get("topic/a.md") is not None
            and blobs.get(snap.manifest["topic/a.md"]) == b"manual"
        ]
        assert len(edits) == 1
        assert edits[0].reason == "user_edit"

        undo = rollback(engine, blobs, project_id, edits[0].id)
        assert undo.created is True
        assert (workdir / "topic" / "a.md").read_text(encoding="utf-8") == "manual"

    def test_rollback_without_pending_edits_creates_no_extra_snapshot(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path
    ) -> None:
        _write(workdir / "topic" / "a.md", "v1")
        snap1 = create_snapshot(engine, blobs, project_id, reason="turn")
        _write(workdir / "topic" / "a.md", "v2")
        create_snapshot(engine, blobs, project_id, reason="turn")

        rollback(engine, blobs, project_id, snap1.id)

        reasons = [snap.reason for snap in list_snapshots(engine, project_id)]
        assert reasons == ["turn", "turn", "rollback"]

    def test_manifest_key_with_dotdot_is_rejected(
        self, engine: Engine, blobs: BlobStore, project_id: str, workdir: Path, data_dir: Path
    ) -> None:
        sha = blobs.put(b"evil")
        bad = insert_snapshot(
            engine, project_id=project_id, manifest={"../escaped.txt": sha}, reason="turn"
        )

        with pytest.raises(ValueError):
            rollback(engine, blobs, project_id, bad.id)

        assert not (workdir.parent / "escaped.txt").exists()


def test_scan_includes_uploads(tmp_path: Path) -> None:
    """上传的文件进快照（设计 2026-10-09 §5.4），回滚时随版本还原。"""
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "ab12cd34-a.md").write_text("x", encoding="utf-8")

    assert "uploads/ab12cd34-a.md" in scan(tmp_path)
