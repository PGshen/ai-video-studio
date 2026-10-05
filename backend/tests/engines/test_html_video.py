"""`engines.render.html.video`：逐帧出图并交给 ffmpeg 编码。

快速用例用一个假的 ffmpeg 脚本（只消费 stdin 并写出文件）和假页面；`slow` 用例用真实的
Chromium 与 ffmpeg。
"""

from __future__ import annotations

import asyncio
import json
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from fixtures.html_engine import fakes
from fixtures.html_engine import projects as fx
from studio.engines.render.html import video
from studio.engines.render.html.assemble import assemble
from studio.engines.render.html.browser import HtmlBrowser, RenderTimeout
from studio.engines.render.html.video import (
    VideoEncodeError,
    VideoRenderError,
    build_encode_command,
    frame_count,
    frame_time,
    render_silent_video,
)

# ---- pure functions ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("duration", "fps", "expected"),
    [(1.0, 30, 30), (6.0, 30, 180), (3.3, 30, 99), (3.31, 30, 100), (0.01, 30, 1), (2.0, 24, 48)],
)
def test_frame_count_rounds_up_without_float_noise(
    duration: float, fps: int, expected: int
) -> None:
    assert frame_count(duration, fps) == expected


def test_frame_time_is_the_start_of_the_frame() -> None:
    assert frame_time(0, 30) == 0.0
    assert frame_time(15, 30) == pytest.approx(0.5)


def test_encode_command_reads_jpeg_from_stdin_and_writes_yuv420p_h264() -> None:
    cmd = build_encode_command(Path("/tmp/o.tmp.mp4"), 30)
    assert cmd[0] == video.FFMPEG
    assert cmd[cmd.index("-f") + 1] == "image2pipe"
    assert cmd[cmd.index("-i") + 1] == "-"
    assert cmd[cmd.index("-c:v", cmd.index("-i")) + 1] == "libx264"
    assert cmd[cmd.index("-vf") + 1].endswith("format=yuv420p")
    assert cmd[cmd.index("-crf") + 1] == "15"
    assert "-an" in cmd
    assert cmd[-1] == "/tmp/o.tmp.mp4"


# ---- fake ffmpeg + fake page -----------------------------------------------------------


def _fake_ffmpeg(tmp_path: Path, *, exit_code: int = 0, die_early: bool = False) -> str:
    script = tmp_path / "fake-ffmpeg"
    body = (
        "#!/bin/sh\n"
        "for last; do :; done\n"
        + ("echo 'boom: bad frame' >&2\nexit 3\n" if die_early else "")
        + "cat > /dev/null\n"
        + (f"echo 'encoder said no' >&2\nexit {exit_code}\n" if exit_code else "")
        + 'echo video > "$last"\n'
    )
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


class CountingPage:
    def __init__(self, *, fail_at: int | None = None, fps: int = 30) -> None:
        self.calls: list[float] = []
        self._fail_at = fail_at
        self._fps = fps
        self.errors: list[str] = []
        self.poisoned = False

    async def render_jpeg(self, t: float) -> bytes:
        self.calls.append(t)
        if self._fail_at is not None and len(self.calls) - 1 == self._fail_at:
            raise RenderTimeout(t, 10.0)
        return fakes.jpeg()

    async def render_hash(self, t: float) -> str:
        return ""

    async def set_timeline(self, timeline: Any) -> None:
        return None

    async def close(self) -> None:
        return None


async def test_renders_every_frame_in_order_and_publishes_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video, "FFMPEG", _fake_ffmpeg(tmp_path))
    page = CountingPage()
    output = tmp_path / "silent.mp4"
    stats = await render_silent_video(page, 1.0, output, fps=30)
    assert stats.frames == 30
    assert page.calls == [pytest.approx(i / 30) for i in range(30)]
    assert output.read_text().strip() == "video"
    assert not list(tmp_path.glob("*.tmp*"))


async def test_progress_is_monotonic_and_ends_at_the_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video, "FFMPEG", _fake_ffmpeg(tmp_path))
    seen: list[tuple[int, int]] = []

    async def on_progress(done: int, total: int) -> None:
        seen.append((done, total))

    await render_silent_video(
        CountingPage(), 0.5, tmp_path / "o.mp4", fps=30, on_progress=on_progress
    )
    assert [done for done, _ in seen] == list(range(1, 16))
    assert {total for _, total in seen} == {15}


async def test_sync_progress_callback_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video, "FFMPEG", _fake_ffmpeg(tmp_path))
    seen: list[int] = []
    await render_silent_video(
        CountingPage(), 0.1, tmp_path / "o.mp4", fps=30, on_progress=lambda d, _t: seen.append(d)
    )
    assert seen == [1, 2, 3]


async def test_frame_failure_names_the_time_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video, "FFMPEG", _fake_ffmpeg(tmp_path))
    output = tmp_path / "o.mp4"
    with pytest.raises(VideoRenderError) as info:
        await render_silent_video(CountingPage(fail_at=7), 1.0, output, fps=30)
    assert "t=0.233" in str(info.value)
    assert not output.exists()
    assert not list(tmp_path.glob("*.tmp*"))


async def test_a_failed_render_keeps_the_previous_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video, "FFMPEG", _fake_ffmpeg(tmp_path))
    output = tmp_path / "o.mp4"
    output.write_text("previous")
    with pytest.raises(VideoRenderError):
        await render_silent_video(CountingPage(fail_at=2), 1.0, output, fps=30)
    assert output.read_text() == "previous"


async def test_ffmpeg_dying_early_reports_its_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video, "FFMPEG", _fake_ffmpeg(tmp_path, die_early=True))
    output = tmp_path / "o.mp4"
    with pytest.raises(VideoEncodeError) as info:
        await render_silent_video(CountingPage(), 3.0, output, fps=30)
    assert "boom: bad frame" in str(info.value)
    assert not output.exists()
    assert not list(tmp_path.glob("*.tmp*"))


async def test_ffmpeg_nonzero_exit_after_all_frames_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video, "FFMPEG", _fake_ffmpeg(tmp_path, exit_code=1))
    output = tmp_path / "o.mp4"
    with pytest.raises(VideoEncodeError) as info:
        await render_silent_video(CountingPage(), 0.1, output, fps=30)
    assert "encoder said no" in str(info.value)
    assert not output.exists()


async def test_cancellation_stops_ffmpeg_and_removes_the_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video, "FFMPEG", _fake_ffmpeg(tmp_path))
    started = asyncio.Event()

    class SlowPage(CountingPage):
        async def render_jpeg(self, t: float) -> bytes:
            started.set()
            await asyncio.sleep(30)
            return fakes.jpeg()

    task = asyncio.create_task(render_silent_video(SlowPage(), 1.0, tmp_path / "o.mp4", fps=30))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(tmp_path.glob("*.tmp*"))


# ---- real Chromium + ffmpeg ------------------------------------------------------------


def _probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


def _one_second_timeline() -> dict[str, Any]:
    return {
        "duration": 1.0,
        "grid": None,
        "sections": [{"id": "s-hook", "label": "开场", "start": 0.0, "end": 1.0}],
        "narration": [
            {
                "scene_id": "s-hook",
                "start": 0.0,
                "end": 1.0,
                "beats": [{"start": 0.1, "end": 0.6, "cue_text": "一句"}],
            }
        ],
        "moments": [],
        "music": None,
        "lyrics": [],
    }


@pytest.mark.slow
async def test_real_render_has_exact_frame_count_and_no_audio(tmp_path: Path) -> None:
    fx.write_project(tmp_path, scenes={"s-hook": fx.PURE_SCENE_PLAIN})
    timeline = _one_second_timeline()
    output = tmp_path / "out" / "silent.mp4"
    seen: list[int] = []
    async with HtmlBrowser(ready_timeout=15, render_timeout=5) as browser:
        page = await browser.open_page(assemble(tmp_path, timeline))
        try:
            stats = await render_silent_video(
                page, 1.0, output, fps=30, on_progress=lambda d, _t: seen.append(d)
            )
        finally:
            await page.close()
    info = _probe(output)
    streams = info["streams"]
    assert [s["codec_type"] for s in streams] == ["video"]
    assert streams[0]["pix_fmt"] == "yuv420p"  # limited range, not the JPEG-flavoured yuvj420p
    assert (streams[0]["width"], streams[0]["height"]) == (1920, 1080)
    assert int(streams[0]["nb_read_frames"]) == 30 == stats.frames
    assert abs(float(info["format"]["duration"]) - 1.0) < 0.1
    assert seen == sorted(seen) and seen[-1] == 30
    # Colours survive the JPEG -> H.264 round trip: scene background is #204060.
    frame = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(output), "-frames:v", "1", str(frame)],
        check=True,
    )
    pixel = Image.open(frame).convert("RGB").getpixel((1800, 1000))
    assert isinstance(pixel, tuple)
    r, g, b = pixel[:3]
    assert max(abs(r - 0x20), abs(g - 0x40), abs(b - 0x60)) < 8


@pytest.mark.slow
async def test_real_scene_error_names_scene_and_time_and_leaves_no_file(tmp_path: Path) -> None:
    timeline = _one_second_timeline()
    fx.write_project(
        tmp_path,
        scenes={
            "s-hook": (
                "module.exports = { draw(ctx, lt, env) {"
                " if (lt > 0.5) throw new Error('late failure');"
                " ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 10, 10); } };\n"
            )
        },
    )
    output = tmp_path / "silent.mp4"
    async with HtmlBrowser(ready_timeout=15, render_timeout=5) as browser:
        page = await browser.open_page(assemble(tmp_path, timeline))
        try:
            with pytest.raises(VideoRenderError) as info:
                await render_silent_video(page, 1.0, output, fps=30)
        finally:
            await page.close()
    message = str(info.value)
    assert "s-hook" in message and "late failure" in message and "t=0.5" in message
    assert not output.exists()
    assert not list(tmp_path.glob("*.tmp*"))
