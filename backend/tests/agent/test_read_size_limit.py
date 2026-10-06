"""Built-in `Read` of a large image is refused: the CLI writes the base64 twice per line, so one
big picture can push a transcript line past the SDK message buffer (found by the MV smoke run)."""

from __future__ import annotations

from pathlib import Path

from studio.agent.claude_scope import MAX_READ_IMAGE_BYTES, read_denial_reason


def _read(workdir: Path, name: str) -> str | None:
    return read_denial_reason(workdir, "Read", {"file_path": str(workdir / name)})


def test_a_small_image_is_readable(tmp_path: Path) -> None:
    (tmp_path / "small.png").write_bytes(b"x" * 1000)
    assert _read(tmp_path, "small.png") is None


def test_a_large_image_is_refused_with_a_pointer_to_the_attached_pictures(tmp_path: Path) -> None:
    (tmp_path / "big.PNG").write_bytes(b"x" * (MAX_READ_IMAGE_BYTES + 1))
    reason = _read(tmp_path, "big.PNG")
    assert reason is not None and "附图" in reason


def test_a_large_text_file_is_not_affected(tmp_path: Path) -> None:
    (tmp_path / "events.json").write_bytes(b"x" * (MAX_READ_IMAGE_BYTES + 1))
    assert _read(tmp_path, "events.json") is None


def test_a_missing_image_is_left_to_the_cli(tmp_path: Path) -> None:
    assert _read(tmp_path, "nope.png") is None
