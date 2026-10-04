"""`engines.render.mix`：旁白轨混音（命令构造为纯函数；真实 ffmpeg 的用例标 slow）。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from studio.engines.render.mix import AudioTrack, MixError, build_mix_command, mix_final

VIDEO = Path("/tmp/v.mp4")
OUT = Path("/tmp/o.mp4")


def test_command_delays_each_track_by_its_start_in_milliseconds() -> None:
    cmd = build_mix_command(
        VIDEO,
        [AudioTrack(Path("/a/1.mp3"), 0.0), AudioTrack(Path("/a/2.mp3"), 4.2506)],
        10.0,
        OUT,
    )
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "adelay=0|0" in graph
    assert "adelay=4251|4251" in graph  # rounded to whole milliseconds
    assert "amix=inputs=2:normalize=0" in graph


def test_command_pins_duration_codec_and_faststart() -> None:
    cmd = build_mix_command(VIDEO, [AudioTrack(Path("/a/1.mp3"), 0.0)], 12.5, OUT)
    assert cmd[cmd.index("-t") + 1] == "12.5"
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-movflags") + 1] == "+faststart"
    assert cmd[-1] == str(OUT)


def test_command_without_tracks_adds_a_silent_audio_stream() -> None:
    cmd = build_mix_command(VIDEO, [], 3.0, OUT)
    assert "-filter_complex" not in cmd
    assert any("anullsrc" in part for part in cmd)
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-t") + 1] == "3"


async def test_music_track_is_reserved_for_a_later_sub_project(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError):
        await mix_final(VIDEO, [], 1.0, tmp_path / "o.mp4", music=AudioTrack(Path("/a/m.mp3"), 0.0))


# ---- real ffmpeg -----------------------------------------------------------------


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _probe(path: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


def _make_video(path: Path, seconds: float) -> None:
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=320x180:r=30:d={seconds}",
        "-pix_fmt",
        "yuv420p",
        str(path),
    )


def _make_tone(path: Path, seconds: float, hz: int = 440) -> None:
    _ffmpeg("-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}", str(path))


def _moov_before_mdat(path: Path) -> bool:
    data = path.read_bytes()
    return data.find(b"moov") != -1 and data.find(b"moov") < data.find(b"mdat")


@pytest.mark.slow
async def test_mix_places_tracks_and_pins_total_duration(tmp_path: Path) -> None:
    video, a1, a2, out = (tmp_path / n for n in ("v.mp4", "a1.mp3", "a2.mp3", "out.mp4"))
    _make_video(video, 6.0)
    _make_tone(a1, 2.0)
    _make_tone(a2, 2.0, hz=880)
    await mix_final(video, [AudioTrack(a1, 0.0), AudioTrack(a2, 3.0)], 6.0, out)
    info = _probe(out)
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert [s["codec_name"] for s in audio] == ["aac"]
    assert abs(float(info["format"]["duration"]) - 6.0) <= 1 / 30 + 0.05
    assert _moov_before_mdat(out)


@pytest.mark.slow
async def test_mix_trims_audio_longer_than_the_timeline(tmp_path: Path) -> None:
    video, a1, out = (tmp_path / n for n in ("v.mp4", "a1.mp3", "out.mp4"))
    _make_video(video, 3.0)
    _make_tone(a1, 8.0)
    await mix_final(video, [AudioTrack(a1, 1.0)], 3.0, out)
    assert abs(float(_probe(out)["format"]["duration"]) - 3.0) <= 0.1


@pytest.mark.slow
async def test_mix_pads_audio_shorter_than_the_timeline(tmp_path: Path) -> None:
    video, a1, out = (tmp_path / n for n in ("v.mp4", "a1.mp3", "out.mp4"))
    _make_video(video, 5.0)
    _make_tone(a1, 1.0)
    await mix_final(video, [AudioTrack(a1, 0.0)], 5.0, out)
    assert abs(float(_probe(out)["format"]["duration"]) - 5.0) <= 0.1


@pytest.mark.slow
async def test_mix_without_tracks_still_has_an_audio_stream(tmp_path: Path) -> None:
    video, out = tmp_path / "v.mp4", tmp_path / "out.mp4"
    _make_video(video, 2.0)
    await mix_final(video, [], 2.0, out)
    kinds = [s["codec_type"] for s in _probe(out)["streams"]]
    assert "audio" in kinds and "video" in kinds


@pytest.mark.slow
async def test_mix_failure_raises_and_leaves_no_output(tmp_path: Path) -> None:
    video, out = tmp_path / "v.mp4", tmp_path / "out.mp4"
    _make_video(video, 1.0)
    with pytest.raises(MixError) as info:
        await mix_final(video, [AudioTrack(tmp_path / "missing.mp3", 0.0)], 1.0, out)
    assert "missing.mp3" in str(info.value)
    assert not out.exists()
    assert not list(tmp_path.glob("*.tmp*"))
