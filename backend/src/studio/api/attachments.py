"""对话消息的附件：校验、分流和给模型的文件说明（设计 2026-10-09 §4–§5、§10）。

- 图片（按魔数识别 png/jpeg/webp/gif）进 `BlobStore` 并作为 `UserInput.images` 发给模型；
  模型不支持图片时改存进工作区 `uploads/`，按文件处理。
- 其他文件写到工作区 `uploads/<请求短 id>-<安全文件名>`，用户文字后面追加一段说明，
  告诉模型文件路径、大小以及能否用读工具直接读（修订 R2）。
- 选题会话没有工作区（`workdir is None`），只收图片。

全部校验在写入任何东西之前完成；写入中途失败时删掉本次已写的文件。本模块不依赖
FastAPI，端点只负责读请求、把 `AttachmentError` 转成 422。
"""

from __future__ import annotations

import base64
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from studio.agent.claude_scope import MAX_READ_IMAGE_BYTES
from studio.agent.events import ImageData
from studio.agent.fallback_tools import MAX_READ_BYTES
from studio.agent.runtime import UserInput
from studio.workspace import BlobStore
from studio.workspace.scope import UPLOADS_DIR

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 6
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 10
MAX_NAME_CHARS = 100

_PDF_AND_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}
# Control characters, plus what Windows forbids in names (`:` would also be an NTFS stream);
# the agent refers to uploads by path, which must pass `check_model_path` (design §5).
_UNSAFE_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"|?*]')


class AttachmentError(ValueError):
    """附件不合法；`str(error)` 是给用户看的中文说明。"""


@dataclass(frozen=True, slots=True)
class IncomingFile:
    name: str
    data: bytes


@dataclass(frozen=True, slots=True)
class AttachmentRecord:
    """一个附件的持久化记录（`turns.attachments` 的一项）。

    `kind="image"` 时 `sha256` 指向 blob；模型不支持图片而被转存成文件时 `path` 也有值。
    `kind="file"` 时 `path` 是工作区相对路径。`binary` 表示内容不是 UTF-8 文本。
    """

    kind: Literal["image", "file"]
    name: str
    size: int
    sha256: str | None
    path: str | None
    binary: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AttachmentRecord:
        return cls(
            kind=raw["kind"],
            name=raw["name"],
            size=raw["size"],
            sha256=raw.get("sha256"),
            path=raw.get("path"),
            binary=bool(raw.get("binary", False)),
        )


@dataclass(frozen=True, slots=True)
class PreparedInput:
    user_input: UserInput
    records: list[AttachmentRecord]
    written: list[Path] = field(default_factory=list)
    """本次写进工作区的文件；之后的步骤失败时由调用方用 `discard` 清掉。"""


def sniff_image(data: bytes) -> str | None:
    """按魔数识别支持的图片格式，返回 media type；不是这几种图片时返回 `None`。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_name(name: str) -> str:
    """只留文件名本身：去掉目录、控制字符和 Windows 不允许的字符、开头的 `.` 和结尾的
    `.`/空格（Windows 会悄悄去掉），截到 100 个字符（保留后缀）。"""
    base = re.split(r"[/\\]", name)[-1]
    base = _UNSAFE_CHARS.sub("_", base).strip().rstrip(". ")
    if not base:
        return "file"
    if base.startswith("."):
        base = "_" + base[1:]
    if len(base) > MAX_NAME_CHARS:
        stem, suffix = os.path.splitext(base)
        suffix = suffix[:20]
        base = (stem[: MAX_NAME_CHARS - len(suffix)] + suffix).rstrip(". ")
    return base


def _is_binary(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return b"\x00" in data


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} kB"
    return f"{size / (1024 * 1024):.1f} MB"


def _unreadable(record: AttachmentRecord, runtime: str) -> bool:
    """修订 R2：读工具读不了（或可能读不全）这个文件。"""
    assert record.path is not None
    if runtime == "openai" and record.binary:
        return True
    if Path(record.path).suffix.lower() in _PDF_AND_IMAGE_SUFFIXES or record.kind == "image":
        return record.size > MAX_READ_IMAGE_BYTES
    return record.size > MAX_READ_BYTES


def file_note(records: list[AttachmentRecord], runtime: str) -> str:
    """给模型的文件说明；没有落进工作区的附件时返回空串。"""
    lines: list[str] = []
    for record in records:
        if record.path is None:
            continue
        line = f"- {record.path}（{_human_size(record.size)}）"
        if record.kind == "image":
            line += "：这是图片，当前模型无法直接查看"
        if _unreadable(record, runtime):
            if runtime == "openai":
                line += "；读工具可能无法直接读取，读不到时请如实告诉用户"
            else:
                line += (
                    "；Read 可能无法直接读取，可以尝试用 Bash 提取文本"
                    "（例如 pdftotext，如果本机安装了的话），读不到时请如实告诉用户"
                )
        lines.append(line)
    if not lines:
        return ""
    return "[用户上传的文件]\n" + "\n".join(lines) + "\n请用读文件工具查看。"


def compose_text(text: str, records: list[AttachmentRecord], runtime: str) -> str:
    """用户原文加文件说明，作为发给模型的 `UserInput.text`。"""
    note = file_note(records, runtime)
    if not note:
        return text
    return f"{text}\n\n{note}" if text else note


def _validate(
    text: str, files: list[IncomingFile], *, workspaceless: bool, supports_vision: bool
) -> list[str | None]:
    if not text.strip() and not files:
        raise AttachmentError("消息不能为空")
    kinds = [sniff_image(f.data) for f in files]
    images = [f for f, kind in zip(files, kinds, strict=True) if kind is not None]
    others = [f for f, kind in zip(files, kinds, strict=True) if kind is None]
    if workspaceless and others:
        raise AttachmentError("选题对话只支持上传图片")
    if workspaceless and images and not supports_vision:
        raise AttachmentError("当前模型不支持图片，请切换模型后再发送")
    if len(images) > MAX_IMAGES:
        raise AttachmentError(f"每条消息最多 {MAX_IMAGES} 张图片")
    if len(others) > MAX_FILES:
        raise AttachmentError(f"每条消息最多 {MAX_FILES} 个文件")
    for image in images:
        if len(image.data) > MAX_IMAGE_BYTES:
            raise AttachmentError(
                f"图片 {image.name} 超过 {MAX_IMAGE_BYTES // (1024 * 1024)} MB 上限"
            )
    for other in others:
        if len(other.data) > MAX_FILE_BYTES:
            raise AttachmentError(
                f"文件 {other.name} 超过 {MAX_FILE_BYTES // (1024 * 1024)} MB 上限"
            )
    return kinds


def _write_upload(workdir: Path, relpath: str, data: bytes) -> Path:
    dest = workdir / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return dest


def discard(written: list[Path]) -> None:
    for path in written:
        path.unlink(missing_ok=True)


def prepare_input(
    text: str,
    files: list[IncomingFile],
    *,
    workdir: Path | None,
    blobs: BlobStore,
    runtime: str,
    supports_vision: bool,
) -> PreparedInput:
    """校验并分流附件，返回发给模型的 `UserInput` 和要持久化的附件记录。"""
    kinds = _validate(text, files, workspaceless=workdir is None, supports_vision=supports_vision)
    prefix = uuid4().hex[:8]
    records: list[AttachmentRecord] = []
    images: list[ImageData] = []
    written: list[Path] = []
    used: set[str] = set()

    def upload_path(name: str) -> str:
        candidate = f"{UPLOADS_DIR}/{prefix}-{safe_name(name)}"
        stem, suffix = os.path.splitext(candidate)
        n = 2
        while candidate in used:
            candidate = f"{stem}-{n}{suffix}"
            n += 1
        used.add(candidate)
        return candidate

    try:
        for incoming, media_type in zip(files, kinds, strict=True):
            size = len(incoming.data)
            if media_type is not None:
                sha256 = blobs.put(incoming.data)
                path: str | None = None
                if supports_vision:
                    encoded = base64.b64encode(incoming.data).decode("ascii")
                    images.append(ImageData(media_type=media_type, data_base64=encoded))
                else:
                    assert workdir is not None
                    path = upload_path(incoming.name)
                    written.append(_write_upload(workdir, path, incoming.data))
                records.append(
                    AttachmentRecord("image", incoming.name, size, sha256, path, binary=True)
                )
                continue
            assert workdir is not None
            path = upload_path(incoming.name)
            written.append(_write_upload(workdir, path, incoming.data))
            records.append(
                AttachmentRecord(
                    "file", incoming.name, size, None, path, binary=_is_binary(incoming.data)
                )
            )
    except BaseException:
        discard(written)
        raise

    user_input = UserInput(text=compose_text(text, records, runtime), images=images)
    return PreparedInput(user_input=user_input, records=records, written=written)
