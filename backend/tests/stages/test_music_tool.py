"""`render_music` 工具（子项目 3 设计 §7.4）：文本、附图、托管文件登记、沙箱不可用。"""

from __future__ import annotations

import base64
import hashlib
import shutil
import sys
from pathlib import Path

import pytest

from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.common.score import tool as music_tool
from studio.stages.common.score.tool import LISTEN_NOTE, RENDER_MUSIC_TOOL

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REF = FIXTURES / "synth_music" / "compose_ref.py"


def identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


@pytest.fixture
def reel(tmp_path: Path) -> Path:
    """An explainer workspace (the `music` stage only serves narrated projects)."""
    target = tmp_path / "upstream" / "narrative"
    target.mkdir(parents=True)
    for name in ("narrative.json", "timing.json"):
        shutil.copyfile(FIXTURES / "animation" / name, target / name)
    (tmp_path / "music").mkdir()
    shutil.copyfile(REF, tmp_path / "music" / "compose.py")
    return tmp_path


def _ctx(workdir: Path, writes: list[tuple[str, str]]) -> ToolContext:
    return ToolContext(
        project_id="p",
        stage="music",
        workdir=workdir,
        record_tool_write=lambda rel, digest: writes.append((rel, digest)),
    )


def test_tool_belongs_to_the_music_and_produce_stages() -> None:
    assert RENDER_MUSIC_TOOL.stages == {"music", "produce"}
    assert RENDER_MUSIC_TOOL.name == "render_music"


async def test_success_returns_text_picture_and_registers_the_managed_files(
    reel: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(music_tool, "sandbox_wrapper", lambda workdir: identity)
    writes: list[tuple[str, str]] = []
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(reel, writes), {})
    assert not result.is_error, result.text
    for needle in ("配乐渲染成功", "BPM 100", "段落 s-hook", "重定时校验通过", "kick", LISTEN_NOTE):
        assert needle in result.text
    assert len(result.images) == 1 and result.images[0].media_type == "image/jpeg"
    assert base64.b64decode(result.images[0].data_base64)[:3] == b"\xff\xd8\xff"
    assert sorted(rel for rel, _ in writes) == sorted(
        f"music/{n}"
        for n in ("music.wav", "events.json", "analysis.json", "analysis.png", "render.json")
    )
    for rel, digest in writes:
        assert hashlib.sha256((reel / rel).read_bytes()).hexdigest() == digest


async def test_failure_is_an_error_without_a_picture_and_registers_nothing(
    reel: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(music_tool, "sandbox_wrapper", lambda workdir: identity)
    (reel / "music" / "compose.py").write_text("raise RuntimeError('boom in script')\n")
    writes: list[tuple[str, str]] = []
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(reel, writes), {})
    assert result.is_error and "boom in script" in result.text and "旧产物没有改动" in result.text
    assert result.images == [] and writes == []


async def test_without_a_sandbox_the_tool_refuses_to_run(
    reel: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(music_tool, "sandbox_wrapper", lambda workdir: None)
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(reel, []), {})
    assert result.is_error and "沙箱" in result.text
    assert not (reel / "music" / "music.wav").exists()


async def test_unavailable_timeline_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(music_tool, "sandbox_wrapper", lambda workdir: identity)
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "compose.py").write_text("pass\n")
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(tmp_path, []), {})
    assert result.is_error and "时间轴不可用" in result.text


@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt only exists on macOS")
async def test_the_real_sandbox_runs_the_reference_script(reel: Path) -> None:
    from studio.agent.shell_sandbox import sandbox_available

    if not sandbox_available():
        pytest.skip("sandbox-exec unavailable")
    writes: list[tuple[str, str]] = []
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(reel, writes), {})
    assert not result.is_error, result.text
    assert (reel / "music" / "music.wav").is_file() and len(writes) == 5


async def test_the_attached_picture_stays_well_under_the_sdk_message_limit(
    reel: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Claude SDK refuses one JSON message over 1 MiB (found by the real-model smoke run):
    the picture goes back as a compressed JPEG; `music/analysis.png` keeps full quality."""
    monkeypatch.setattr(music_tool, "sandbox_wrapper", lambda workdir: identity)
    result = await invoke_tool(RENDER_MUSIC_TOOL, _ctx(reel, []), {})
    assert not result.is_error, result.text
    image = result.images[0]
    assert image.media_type == "image/jpeg"
    raw = base64.b64decode(image.data_base64)
    assert raw[:3] == b"\xff\xd8\xff" and len(raw) <= 300_000
    assert (reel / "music" / "analysis.png").read_bytes()[:4] == b"\x89PNG"


def test_a_noisy_picture_is_lowered_in_quality_then_shrunk_until_it_fits() -> None:
    """Exercises the loop, not just the first quality step: noise does not fit at any quality of
    the full size."""
    import io

    import numpy as np
    from PIL import Image

    pixels = np.random.default_rng(3).integers(0, 256, (1000, 1800, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    out = music_tool.compress_picture(buffer.getvalue())
    assert len(out) <= 300_000
    assert Image.open(io.BytesIO(out)).width < 1800  # had to shrink
