"""The silent-video cache key covers everything that changes the rendered bytes (TD-70)."""

from __future__ import annotations

from pathlib import Path

import pytest

from studio import worker_html
from studio.engines.render.html import video
from studio.engines.render.html.assemble import AssembledPage


def _page(tmp_path: Path, font: bytes = b"font-v1") -> AssembledPage:
    font_file = tmp_path / "face.woff2"
    font_file.write_bytes(font)
    return AssembledPage(
        html="<canvas></canvas>", routes={"fonts/face.woff2": font_file}, scripts={"a.js": "1"}
    )


def test_the_key_is_deterministic(tmp_path: Path) -> None:
    page = _page(tmp_path)
    assert worker_html._cache_key(page, "tl", 30) == worker_html._cache_key(page, "tl", 30)


def test_a_changed_bundled_font_changes_the_key(tmp_path: Path) -> None:
    before = worker_html._cache_key(_page(tmp_path, b"font-v1"), "tl", 30)
    after = worker_html._cache_key(_page(tmp_path, b"font-v2"), "tl", 30)
    assert before != after


def test_changed_encoding_parameters_change_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _page(tmp_path)
    before = worker_html._cache_key(page, "tl", 30)
    original = worker_html.encode_signature
    monkeypatch.setattr(
        worker_html, "encode_signature", lambda fps: [*original(fps), "-preset", "slow"]
    )
    assert worker_html._cache_key(page, "tl", 30) != before


def test_the_encode_command_is_the_signature_plus_the_output_path() -> None:
    out = Path("/tmp/x.mp4")
    assert video.build_encode_command(out, 30) == [*video.encode_signature(30), str(out)]
    assert "/tmp/x.mp4" not in video.encode_signature(30)
