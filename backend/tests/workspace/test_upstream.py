from __future__ import annotations

import stat
from pathlib import Path

from studio.workspace.blobs import BlobStore
from studio.workspace.upstream import materialize_upstream


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


class TestMaterializeUpstream:
    def test_copies_only_that_stage_product_dir(self, blobs: BlobStore, workdir: Path) -> None:
        brief_sha = blobs.put(b"# brief")
        notes_sha = blobs.put(b"note")
        style_sha = blobs.put(b"# style")
        topic_manifest = {
            "topic/brief.md": brief_sha,
            "topic/notes/a.md": notes_sha,
            "style/STYLE.md": style_sha,
        }

        materialize_upstream(workdir, blobs, {"topic": topic_manifest})

        assert (workdir / "upstream" / "topic" / "brief.md").read_bytes() == b"# brief"
        assert (workdir / "upstream" / "topic" / "notes" / "a.md").read_bytes() == b"note"
        assert not (workdir / "upstream" / "style").exists()

    def test_files_are_read_only(self, blobs: BlobStore, workdir: Path) -> None:
        sha = blobs.put(b"# brief")
        materialize_upstream(workdir, blobs, {"topic": {"topic/brief.md": sha}})

        mode = (workdir / "upstream" / "topic" / "brief.md").stat().st_mode
        assert not (mode & stat.S_IWUSR)

    def test_stage_with_no_finalized_snapshot_is_skipped(
        self, blobs: BlobStore, workdir: Path
    ) -> None:
        materialize_upstream(workdir, blobs, {"topic": None})

        assert not (workdir / "upstream" / "topic").exists()

    def test_rebuilds_from_scratch_each_call(self, blobs: BlobStore, workdir: Path) -> None:
        sha1 = blobs.put(b"v1")
        materialize_upstream(workdir, blobs, {"topic": {"topic/brief.md": sha1}})
        assert (workdir / "upstream" / "topic" / "brief.md").read_bytes() == b"v1"

        sha2 = blobs.put(b"v2")
        materialize_upstream(workdir, blobs, {"topic": {"topic/brief.md": sha2}})

        assert (workdir / "upstream" / "topic" / "brief.md").read_bytes() == b"v2"

    def test_file_written_by_agent_into_upstream_disappears_after_rematerialize(
        self, blobs: BlobStore, workdir: Path
    ) -> None:
        sha = blobs.put(b"# brief")
        materialize_upstream(workdir, blobs, {"topic": {"topic/brief.md": sha}})

        # 模拟 agent 通过 Shell 往 upstream/ 里写文件（应该在下一轮物化时消失）。
        (workdir / "upstream" / "topic" / "hack.md").write_text("hacked", encoding="utf-8")

        materialize_upstream(workdir, blobs, {"topic": {"topic/brief.md": sha}})

        assert not (workdir / "upstream" / "topic" / "hack.md").exists()

    def test_leftover_symlink_in_upstream_does_not_chmod_external_target(
        self, blobs: BlobStore, workdir: Path, tmp_path: Path
    ) -> None:
        """`upstream/` 是排除目录，不受越界检查约束；上一轮如果被写入了一个
        指向工作区外部的符号链接，下一次物化清空 `upstream/` 时，不应该跟随
        这个符号链接去修改外部目标的权限，只需要把符号链接本身删掉。
        """
        sha = blobs.put(b"# brief")
        materialize_upstream(workdir, blobs, {"topic": {"topic/brief.md": sha}})

        external_target = tmp_path / "external.txt"
        external_target.write_text("secret", encoding="utf-8")
        external_target.chmod(0o400)
        original_mode = external_target.stat().st_mode
        (workdir / "upstream" / "topic" / "escape.txt").symlink_to(external_target)

        materialize_upstream(workdir, blobs, {"topic": {"topic/brief.md": sha}})

        assert not (workdir / "upstream" / "topic" / "escape.txt").exists()
        assert external_target.stat().st_mode == original_mode
