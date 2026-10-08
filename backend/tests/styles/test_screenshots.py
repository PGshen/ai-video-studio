"""风格截图：图片规范化、文件名规则、目录列出。"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from studio.styles.screenshots import (
    MAX_EDGE,
    MAX_SCREENSHOTS,
    ScreenshotError,
    is_screenshot_name,
    list_screenshots,
    normalize_image,
    renumbered,
    screenshot_name,
)


def _encode(fmt: str, size: tuple[int, int] = (64, 32), **save: object) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, format=fmt, **save)
    return buffer.getvalue()


def _opened(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_supported_formats_become_webp(fmt: str) -> None:
    image = _opened(normalize_image(_encode(fmt)))
    assert image.format == "WEBP"
    assert image.size == (64, 32)


def test_large_images_are_scaled_to_the_max_edge() -> None:
    image = _opened(normalize_image(_encode("PNG", (4000, 1000))))
    assert image.size == (MAX_EDGE, MAX_EDGE // 4)


def test_exif_orientation_is_applied() -> None:
    source = Image.new("RGB", (80, 40), (0, 0, 255))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to display
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", exif=exif)
    assert _opened(normalize_image(buffer.getvalue())).size == (40, 80)


def test_transparency_is_kept() -> None:
    buffer = io.BytesIO()
    Image.new("RGBA", (10, 10), (255, 0, 0, 0)).save(buffer, format="PNG")
    assert _opened(normalize_image(buffer.getvalue())).mode == "RGBA"


@pytest.mark.parametrize(
    "data",
    [b"", b"just text, not an image", _encode("GIF"), _encode("PNG")[:40]],
    ids=["empty", "text", "gif", "truncated-png"],
)
def test_non_images_and_unsupported_formats_are_rejected(data: bytes) -> None:
    with pytest.raises(ScreenshotError):
        normalize_image(data)


def test_images_with_too_many_pixels_are_rejected_before_decoding() -> None:
    # 10000 x 10000 = 100M pixels of a flat colour: tiny as PNG, huge once decoded.
    with pytest.raises(ScreenshotError, match="像素"):
        normalize_image(_encode("PNG", (10000, 10000)))


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("001-3fa2c9e01b7d.webp", True),
        ("012-0123456789ab.webp", True),
        ("1-3fa2c9e01b7d.webp", False),
        ("001-3fa2c9e01b7d.png", False),
        ("001-3FA2C9E01B7D.webp", False),
        ("001-3fa2c9e01b7.webp", False),
        ("../001-3fa2c9e01b7d.webp", False),
        ("", False),
    ],
)
def test_screenshot_name_rules(name: str, valid: bool) -> None:
    assert is_screenshot_name(name) is valid


def test_screenshot_name_embeds_index_and_content_hash() -> None:
    data = b"abc"
    digest = hashlib.sha256(data).hexdigest()[:12]
    assert screenshot_name(0, data) == f"001-{digest}.webp"
    assert screenshot_name(11, data) == f"012-{digest}.webp"
    assert is_screenshot_name(screenshot_name(3, data))


def test_list_screenshots_returns_sorted_valid_names(tmp_path: Path) -> None:
    (tmp_path / "002-bbbbbbbbbbbb.webp").write_bytes(b"x")
    (tmp_path / "001-aaaaaaaaaaaa.webp").write_bytes(b"x")
    assert list_screenshots(tmp_path) == (
        ["001-aaaaaaaaaaaa.webp", "002-bbbbbbbbbbbb.webp"],
        [],
    )


def test_list_screenshots_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert list_screenshots(tmp_path / "nope") == ([], [])


def test_list_screenshots_reports_symlinks_subdirs_and_bad_names(tmp_path: Path) -> None:
    (tmp_path / "001-aaaaaaaaaaaa.webp").write_bytes(b"x")
    (tmp_path / "link.webp").symlink_to(tmp_path / "001-aaaaaaaaaaaa.webp")
    (tmp_path / "sub").mkdir()
    (tmp_path / "notes.txt").write_text("hi")
    (tmp_path / ".DS_Store").write_bytes(b"")
    names, problems = list_screenshots(tmp_path)
    assert names == ["001-aaaaaaaaaaaa.webp"]
    assert len(problems) == 3
    assert all("screenshots/" in p for p in problems)


def test_list_screenshots_reports_too_many(tmp_path: Path) -> None:
    for i in range(MAX_SCREENSHOTS + 1):
        (tmp_path / f"{i + 1:03d}-aaaaaaaaaaaa.webp").write_bytes(b"x")
    names, problems = list_screenshots(tmp_path)
    assert len(names) == MAX_SCREENSHOTS + 1
    assert any(str(MAX_SCREENSHOTS) in p for p in problems)


def test_renumbered_keeps_the_hash_and_follows_the_given_order() -> None:
    assert renumbered(["003-cccccccccccc.webp", "001-aaaaaaaaaaaa.webp"]) == [
        ("003-cccccccccccc.webp", "001-cccccccccccc.webp"),
        ("001-aaaaaaaaaaaa.webp", "002-aaaaaaaaaaaa.webp"),
    ]
