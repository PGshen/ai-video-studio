"""Offline checks for the smoke-test helpers (run by `make check`, no model calls)."""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.topic import STAGE as TOPIC

from .support import (
    SMOKE_COLOURS,
    SmokeStage,
    make_two_colour_png,
    mentions_colours,
    smoke_image_tool,
)


def _chunks(png: bytes) -> list[tuple[bytes, bytes]]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    chunks: list[tuple[bytes, bytes]] = []
    pos = 8
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        kind = png[pos + 4 : pos + 8]
        data = png[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", png[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(kind + data)
        chunks.append((kind, data))
        pos += 12 + length
    return chunks


def test_png_is_valid_and_split_into_two_colours() -> None:
    left, right = (0, 0, 255), (255, 255, 0)
    png = make_two_colour_png(8, 2, left, right)
    chunks = _chunks(png)
    assert [kind for kind, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    width, height, depth, colour_type = struct.unpack(">IIBB", chunks[0][1][:10])
    assert (width, height, depth, colour_type) == (8, 2, 8, 2)
    raw = zlib.decompress(chunks[1][1])
    row = raw[: 1 + 8 * 3]
    assert row[0] == 0  # filter: none
    pixels = [tuple(row[1 + i * 3 : 4 + i * 3]) for i in range(8)]
    assert pixels == [left] * 4 + [right] * 4


async def test_smoke_image_tool_returns_png_without_naming_the_colours(tmp_path: Path) -> None:
    ctx = ToolContext("p", "topic", tmp_path, lambda _path, _sha: None)
    result = await invoke_tool(smoke_image_tool(), ctx, {})
    assert not result.is_error
    assert [image.media_type for image in result.images] == ["image/png"]
    _chunks(base64.b64decode(result.images[0].data_base64))
    assert not mentions_colours(result.text)


def test_mentions_colours_needs_both_colours_in_any_language() -> None:
    assert mentions_colours("左边是蓝色，右边是黄色")
    assert mentions_colours("Left half BLUE, right half yellow.")
    assert not mentions_colours("只看到蓝色")
    assert set(SMOKE_COLOURS) == {"blue", "yellow"}


def test_smoke_stage_adds_the_tool_and_keeps_everything_else() -> None:
    stage = SmokeStage(TOPIC)
    assert stage.name == "topic"
    assert [tool.name for tool in stage.tools()] == ["smoke_image"]
    assert stage.write_scope() == TOPIC.write_scope()
    assert stage.allow_web is False
