"""`api/attachments.py`：上传附件的校验、分流与给模型的文件说明（设计 2026-10-09 §4–§5、§10）。"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from studio.agent.claude_scope import MAX_READ_IMAGE_BYTES
from studio.agent.fallback_tools import MAX_READ_BYTES
from studio.api.attachments import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    AttachmentError,
    AttachmentRecord,
    IncomingFile,
    file_note,
    prepare_input,
    safe_name,
    sniff_image,
)
from studio.workspace import BlobStore

PNG = b"\x89PNG\r\n\x1a\n" + b"png-body"
JPEG = b"\xff\xd8\xff" + b"jpeg-body"
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"webp-body"
GIF = b"GIF89a" + b"gif-body"


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "blobs")


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


def _prepare(
    text: str,
    files: list[IncomingFile],
    *,
    workdir: Path | None,
    blobs: BlobStore,
    runtime: str = "claude",
    supports_vision: bool = True,
):
    return prepare_input(
        text,
        files,
        workdir=workdir,
        blobs=blobs,
        runtime=runtime,
        supports_vision=supports_vision,
    )


class TestSniffImage:
    @pytest.mark.parametrize(
        ("data", "media_type"),
        [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp"), (GIF, "image/gif")],
    )
    def test_recognises_supported_formats(self, data: bytes, media_type: str) -> None:
        assert sniff_image(data) == media_type

    def test_text_named_png_is_not_an_image(self) -> None:
        assert sniff_image(b"just some text") is None


class TestSafeName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("../../etc/passwd", "passwd"),
            ("/abs/path/report.pdf", "report.pdf"),
            ("C:\\Users\\me\\notes.txt", "notes.txt"),
            (".hidden", "_hidden"),
            ("论文 草稿.md", "论文 草稿.md"),
            ("a\x00b\nc.txt", "a_b_c.txt"),
            ("", "file"),
            ("..", "file"),
        ],
    )
    def test_keeps_only_a_harmless_basename(self, raw: str, expected: str) -> None:
        assert safe_name(raw) == expected

    def test_truncates_long_names_to_100_chars_keeping_suffix(self) -> None:
        name = safe_name("x" * 300 + ".pdf")
        assert len(name) == 100
        assert name.endswith(".pdf")


class TestPrepareInput:
    def test_images_become_user_input_images_and_blobs(
        self, workdir: Path, blobs: BlobStore
    ) -> None:
        prepared = _prepare("看图", [IncomingFile("a.png", PNG)], workdir=workdir, blobs=blobs)

        assert prepared.user_input.text == "看图"
        assert len(prepared.user_input.images) == 1
        image = prepared.user_input.images[0]
        assert image.media_type == "image/png"
        assert base64.b64decode(image.data_base64) == PNG
        (record,) = prepared.records
        assert record.kind == "image"
        assert record.sha256 is not None and blobs.get(record.sha256) == PNG
        assert record.path is None
        assert prepared.written == []
        assert not (workdir / "uploads").exists()

    def test_files_land_in_uploads_with_note(self, workdir: Path, blobs: BlobStore) -> None:
        prepared = _prepare(
            "读一下", [IncomingFile("notes.md", b"# hi")], workdir=workdir, blobs=blobs
        )

        (record,) = prepared.records
        assert record.kind == "file"
        assert record.path is not None
        assert record.path.startswith("uploads/") and record.path.endswith("-notes.md")
        assert (workdir / record.path).read_bytes() == b"# hi"
        assert prepared.written == [workdir / record.path]
        assert prepared.user_input.text.startswith("读一下\n\n[用户上传的文件]")
        assert record.path in prepared.user_input.text
        assert prepared.user_input.images == []

    def test_same_named_files_do_not_overwrite_each_other(
        self, workdir: Path, blobs: BlobStore
    ) -> None:
        prepared = _prepare(
            "",
            [IncomingFile("a.txt", b"one"), IncomingFile("a.txt", b"two")],
            workdir=workdir,
            blobs=blobs,
        )

        paths = [r.path for r in prepared.records]
        assert len(set(paths)) == 2
        assert sorted((workdir / p).read_bytes() for p in paths if p) == [b"one", b"two"]

    def test_duplicate_image_is_recorded_twice(self, workdir: Path, blobs: BlobStore) -> None:
        prepared = _prepare(
            "",
            [IncomingFile("a.png", PNG), IncomingFile("b.png", PNG)],
            workdir=workdir,
            blobs=blobs,
        )

        assert [r.name for r in prepared.records] == ["a.png", "b.png"]
        assert len(prepared.user_input.images) == 2

    def test_text_and_attachments_cannot_both_be_empty(
        self, workdir: Path, blobs: BlobStore
    ) -> None:
        with pytest.raises(AttachmentError):
            _prepare("   ", [], workdir=workdir, blobs=blobs)

    def test_empty_text_with_attachment_is_fine(self, workdir: Path, blobs: BlobStore) -> None:
        prepared = _prepare("", [IncomingFile("a.png", PNG)], workdir=workdir, blobs=blobs)
        assert prepared.records

    def test_workspaceless_session_rejects_files(self, blobs: BlobStore) -> None:
        with pytest.raises(AttachmentError, match="选题对话只支持上传图片"):
            _prepare("x", [IncomingFile("a.txt", b"t")], workdir=None, blobs=blobs)

    def test_workspaceless_session_accepts_images(self, blobs: BlobStore) -> None:
        prepared = _prepare("x", [IncomingFile("a.png", PNG)], workdir=None, blobs=blobs)
        assert len(prepared.user_input.images) == 1

    def test_workspaceless_session_without_vision_rejects_images(self, blobs: BlobStore) -> None:
        with pytest.raises(AttachmentError, match="当前模型不支持图片"):
            _prepare(
                "x", [IncomingFile("a.png", PNG)], workdir=None, blobs=blobs, supports_vision=False
            )

    def test_without_vision_images_are_stored_as_files(
        self, workdir: Path, blobs: BlobStore
    ) -> None:
        prepared = _prepare(
            "x", [IncomingFile("a.png", PNG)], workdir=workdir, blobs=blobs, supports_vision=False
        )

        assert prepared.user_input.images == []
        (record,) = prepared.records
        assert record.kind == "image"
        assert record.sha256 is not None
        assert record.path is not None and (workdir / record.path).read_bytes() == PNG
        assert "当前模型无法直接查看" in prepared.user_input.text

    def test_image_at_limit_is_accepted(self, workdir: Path, blobs: BlobStore) -> None:
        data = PNG + b"\x00" * (MAX_IMAGE_BYTES - len(PNG))
        assert _prepare("", [IncomingFile("a.png", data)], workdir=workdir, blobs=blobs).records

    def test_image_over_limit_is_rejected(self, workdir: Path, blobs: BlobStore) -> None:
        data = PNG + b"\x00" * (MAX_IMAGE_BYTES - len(PNG) + 1)
        with pytest.raises(AttachmentError, match="图片"):
            _prepare("", [IncomingFile("a.png", data)], workdir=workdir, blobs=blobs)

    def test_too_many_images_rejected(self, workdir: Path, blobs: BlobStore) -> None:
        files = [IncomingFile(f"{i}.png", PNG) for i in range(MAX_IMAGES + 1)]
        with pytest.raises(AttachmentError):
            _prepare("", files, workdir=workdir, blobs=blobs)

    def test_file_at_limit_is_accepted(self, workdir: Path, blobs: BlobStore) -> None:
        data = b"a" * MAX_FILE_BYTES
        assert _prepare("", [IncomingFile("a.txt", data)], workdir=workdir, blobs=blobs).records

    def test_file_over_limit_is_rejected_without_writing(
        self, workdir: Path, blobs: BlobStore
    ) -> None:
        files = [
            IncomingFile("ok.txt", b"ok"),
            IncomingFile("big.txt", b"a" * (MAX_FILE_BYTES + 1)),
        ]
        with pytest.raises(AttachmentError, match="文件"):
            _prepare("", files, workdir=workdir, blobs=blobs)
        assert not (workdir / "uploads").exists()

    def test_too_many_files_rejected(self, workdir: Path, blobs: BlobStore) -> None:
        files = [IncomingFile(f"{i}.txt", b"t") for i in range(MAX_FILES + 1)]
        with pytest.raises(AttachmentError):
            _prepare("", files, workdir=workdir, blobs=blobs)

    def test_record_round_trips_through_dict(self, workdir: Path, blobs: BlobStore) -> None:
        prepared = _prepare("", [IncomingFile("a.bin", b"\x00\xff")], workdir=workdir, blobs=blobs)
        (record,) = prepared.records
        assert AttachmentRecord.from_dict(record.to_dict()) == record
        assert record.binary is True


class TestFileNote:
    def _file(self, name: str, size: int, *, binary: bool = False) -> AttachmentRecord:
        return AttachmentRecord(
            kind="file",
            name=name,
            size=size,
            sha256=None,
            path=f"uploads/ab12cd34-{name}",
            binary=binary,
        )

    def test_empty_when_no_files(self) -> None:
        image = AttachmentRecord(kind="image", name="a.png", size=3, sha256="x", path=None)
        assert file_note([image], "claude") == ""

    def test_small_text_file_is_readable(self) -> None:
        note = file_note([self._file("a.md", 10)], "claude")
        assert note.startswith("[用户上传的文件]")
        assert "uploads/ab12cd34-a.md" in note
        assert "无法直接读取" not in note

    def test_big_pdf_on_claude_suggests_bash(self) -> None:
        note = file_note([self._file("p.pdf", MAX_READ_IMAGE_BYTES + 1, binary=True)], "claude")
        assert "可能无法直接读取" in note
        assert "pdftotext" in note

    def test_small_pdf_on_claude_is_readable(self) -> None:
        note = file_note([self._file("p.pdf", MAX_READ_IMAGE_BYTES, binary=True)], "claude")
        assert "无法直接读取" not in note

    def test_binary_file_on_openai_is_unreadable(self) -> None:
        note = file_note([self._file("p.pdf", 10, binary=True)], "openai")
        assert "无法直接读取" in note
        assert "如实告诉用户" in note

    def test_huge_text_file_is_unreadable(self) -> None:
        note = file_note([self._file("a.txt", MAX_READ_BYTES + 1)], "openai")
        assert "无法直接读取" in note
