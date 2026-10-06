"""Budget for tool results that go back to the model (T1 of produce-stage).

The Claude CLI writes an image twice into one JSON message (`message.content[].content[]` and the
top-level `toolUseResult[]`), measured on 2026-10-06 from a real session transcript: a 394 kB
JPEG (525 324 base64 bytes) made a 1 054 050 byte line, over the SDK's 1 048 576 limit. So every
budget here counts each image — and each text — twice.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import BaseModel

from studio.agent.events import ImageData
from studio.agent.tools import (
    MAX_IMAGE_BASE64_BYTES,
    MAX_TEXT_BYTES,
    ToolContext,
    ToolResult,
    ToolSpec,
    invoke_tool,
)
from studio.stages.common import picture
from studio.stages.common.picture import compress_png, limit_for

CLI_MESSAGE_LIMIT = 1_048_576
SAFE_MESSAGE_LIMIT = 900_000
"""What a CLI line built from one tool result must stay under (leaves ~150 kB of margin)."""


class _NoArgs(BaseModel):
    pass


def _noisy_png(width: int = 1800, height: int = 1000) -> bytes:
    pixels = np.random.default_rng(7).integers(0, 256, (height, width, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    return buffer.getvalue()


def _cli_line(result: ToolResult) -> bytes:
    """A line shaped like the CLI's: the same content once in `message`, once in `toolUseResult`."""
    content: list[dict] = [{"type": "text", "text": result.text}]
    content += [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": i.media_type, "data": i.data_base64},
        }
        for i in result.images
    ]
    line = {
        "type": "user",
        "message": {"content": [{"content": content}]},
        "toolUseResult": content,
    }
    return json.dumps(line, ensure_ascii=False).encode("utf-8")


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        project_id="p", stage="topic", workdir=tmp_path, record_tool_write=lambda *_: None
    )


def _spec(result: ToolResult) -> ToolSpec:
    return ToolSpec("big", "大结果", _NoArgs, {"topic"}, lambda _ctx, _args: result)


def test_one_compressed_picture_fits_the_message_twice() -> None:
    jpeg = compress_png(_noisy_png())
    image = ImageData("image/jpeg", base64.b64encode(jpeg).decode("ascii"))
    assert len(image.data_base64) <= MAX_IMAGE_BASE64_BYTES
    assert len(_cli_line(ToolResult(text="x" * 5_000, images=[image]))) < SAFE_MESSAGE_LIMIT


@pytest.mark.parametrize("count", [1, 2, 3, 4, 6, 16])
def test_per_picture_limits_add_up_to_the_shared_budget(count: int) -> None:
    per_picture = limit_for(count)
    # The floor in `limit_for` may exceed the share for many pictures; the contact-sheet tools
    # never ask for more than a handful, and `invoke_tool` is the backstop for the rest.
    if count <= 8:
        assert count * per_picture * 4 // 3 <= MAX_IMAGE_BASE64_BYTES + 4 * count
    assert per_picture <= picture.DEFAULT_LIMIT_BYTES


def test_default_limits_follow_the_base64_budget() -> None:
    assert picture.DEFAULT_LIMIT_BYTES * 4 // 3 <= MAX_IMAGE_BASE64_BYTES + 4
    assert picture.TOTAL_LIMIT_BYTES * 4 // 3 <= MAX_IMAGE_BASE64_BYTES + 4


async def test_invoke_tool_truncates_long_text(tmp_path: Path) -> None:
    long_text = "事" * 30_000  # 90 000 UTF-8 bytes
    result = await invoke_tool(_spec(ToolResult(text=long_text)), _ctx(tmp_path), {})
    assert not result.is_error
    assert len(result.text.encode("utf-8")) <= MAX_TEXT_BYTES + 400
    assert "已截断" in result.text
    assert result.text.startswith("事事事")


async def test_invoke_tool_keeps_short_text_untouched(tmp_path: Path) -> None:
    result = await invoke_tool(_spec(ToolResult(text="短文本")), _ctx(tmp_path), {})
    assert result.text == "短文本"


async def test_invoke_tool_drops_pictures_over_the_shared_budget(tmp_path: Path) -> None:
    big = ImageData("image/jpeg", "A" * 300_000)
    over = ToolResult(text="结果", images=[big, big])  # 600 kB base64 in total
    result = await invoke_tool(_spec(over), _ctx(tmp_path), {})
    assert result.images == []
    assert "附图" in result.text and "结果" in result.text
    assert len(_cli_line(result)) < SAFE_MESSAGE_LIMIT


async def test_invoke_tool_keeps_pictures_within_the_budget(tmp_path: Path) -> None:
    ok = ImageData("image/jpeg", "A" * 150_000)
    result = await invoke_tool(_spec(ToolResult(text="结果", images=[ok, ok])), _ctx(tmp_path), {})
    assert len(result.images) == 2


async def test_worst_case_result_stays_under_the_cli_limit(tmp_path: Path) -> None:
    """Both caps at once: max text and max pictures, written twice."""
    images = [ImageData("image/jpeg", "A" * (MAX_IMAGE_BASE64_BYTES // 2))] * 2
    result = await invoke_tool(
        _spec(ToolResult(text="事" * 30_000, images=images)), _ctx(tmp_path), {}
    )
    assert len(_cli_line(result)) < CLI_MESSAGE_LIMIT
