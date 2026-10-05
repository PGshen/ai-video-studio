"""`engines.render.mix`：旁白轨混音（命令构造为纯函数；真实 ffmpeg 的用例标 slow）。"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from studio.engines.render.mix import (
    AudioTrack,
    MixError,
    MusicMix,
    build_mix_command,
    mix_final,
)

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


def test_a_clip_is_cut_at_the_end_of_its_scene_before_it_is_delayed() -> None:
    cmd = build_mix_command(
        VIDEO,
        [AudioTrack(Path("/a/1.mp3"), 0.0, max_seconds=1.4), AudioTrack(Path("/a/2.mp3"), 1.4)],
        3.0,
        OUT,
    )
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:a]atrim=end=1.4,adelay=0|0[a0]" in graph
    assert "[2:a]adelay=1400|1400[a1]" in graph  # no limit given: untouched


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


def _graph(cmd: list[str]) -> str:
    return cmd[cmd.index("-filter_complex") + 1]


MUSIC = Path("/a/music.wav")
NARRATION = [AudioTrack(Path("/a/1.mp3"), 0.0), AudioTrack(Path("/a/2.mp3"), 2.0)]


def test_a_missing_music_mix_leaves_the_command_unchanged() -> None:
    assert build_mix_command(VIDEO, NARRATION, 6.0, OUT) == build_mix_command(
        VIDEO, NARRATION, 6.0, OUT, music=None
    )


def test_music_only_is_resampled_trimmed_faded_and_pinned_to_the_duration() -> None:
    cmd = build_mix_command(VIDEO, [], 7.5, OUT, music=MusicMix(AudioTrack(MUSIC, 0.0)))
    graph = _graph(cmd)
    assert cmd.count("-i") == 2 and str(MUSIC) in cmd
    assert "aresample=44100" in graph and "channel_layouts=stereo" in graph
    assert "afade=t=in:st=0:d=0.015" in graph and "afade=t=out:st=7.485:d=0.015" in graph
    assert "apad=whole_dur=7.5" in graph and "atrim=end=7.5" in graph
    assert "volume=" not in graph  # no gain asked for
    assert "sidechaincompress" not in graph and "amix" not in graph
    assert cmd[cmd.index("-map", cmd.index("-map") + 1) + 1] == "[aout]"
    assert not re.search(r"apad(?!=)", graph)


def test_gain_and_long_fades_go_into_the_graph() -> None:
    music = MusicMix(AudioTrack(MUSIC, 0.0, gain_db=-8.0), fade_in=1.0, fade_out=1.5)
    graph = _graph(build_mix_command(VIDEO, [], 10.0, OUT, music=music))
    assert "volume=-8dB" in graph
    assert "afade=t=in:st=0:d=1" in graph and "afade=t=out:st=8.5:d=1.5" in graph


def test_music_under_narration_is_ducked_by_a_sidechain_of_the_narration_bus() -> None:
    music = MusicMix(AudioTrack(MUSIC, 0.0, gain_db=-8.0), duck_under_narration=True)
    cmd = build_mix_command(VIDEO, NARRATION, 6.0, OUT, music=music)
    graph = _graph(cmd)
    assert cmd.count("-i") == 4  # video, two narration clips, music
    assert str(MUSIC) in cmd[cmd.index(str(NARRATION[1].path)) :]
    assert "asplit=2" in graph and "sidechaincompress=" in graph
    assert graph.count("amix=") == 2  # narration bus, then bus + ducked music
    assert "amix=inputs=2:normalize=0:duration=longest" in graph.split("sidechaincompress")[1]
    assert "apad=whole_dur=6" in graph and "atrim=end=6" in graph


def test_music_under_narration_without_ducking_is_just_mixed_in() -> None:
    music = MusicMix(AudioTrack(MUSIC, 0.0), duck_under_narration=False)
    graph = _graph(build_mix_command(VIDEO, NARRATION, 6.0, OUT, music=music))
    assert "sidechaincompress" not in graph and "asplit" not in graph
    assert "amix=inputs=3:normalize=0" in graph


def test_ducking_with_no_narration_has_nothing_to_duck_under() -> None:
    music = MusicMix(AudioTrack(MUSIC, 0.0), duck_under_narration=True)
    assert "sidechaincompress" not in _graph(build_mix_command(VIDEO, [], 4.0, OUT, music=music))


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


def test_audio_graph_is_finite_so_ffmpeg_cannot_spin_on_an_endless_pad() -> None:
    cmd = build_mix_command(VIDEO, [AudioTrack(Path("/a/1.mp3"), 0.0)], 3.0, OUT)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "apad=whole_dur=3" in graph
    assert "atrim=end=3" in graph
    assert not re.search(r"apad(?!=)", graph)  # a bare `apad` pads forever


@pytest.mark.slow
async def test_mix_terminates_when_the_narration_exactly_fills_the_timeline(tmp_path: Path) -> None:
    """回归：旁白总长恰好等于视频时长（真实成片的常态）时，无限 `apad` 会让 ffmpeg 一直写下去。

    视频用引擎自己的编码路径生成（`render_silent_video`），它的时间戳形态正是触发条件。
    """
    from fixtures.html_engine import fakes
    from studio.engines.render.html.video import render_silent_video

    class Frames:
        errors: list[str] = []
        poisoned = False

        async def render_jpeg(self, t: float) -> bytes:
            return fakes.jpeg()

        async def render_hash(self, t: float) -> str:
            return ""

        async def set_timeline(self, timeline: object) -> None:
            return None

        async def close(self) -> None:
            return None

    video, a1, a2, out = (tmp_path / n for n in ("v.mp4", "a1.wav", "a2.wav", "out.mp4"))
    await render_silent_video(Frames(), 3.0, video, fps=30)
    for path, seconds in ((a1, 1.4), (a2, 1.6)):
        _ffmpeg(
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-ar", "24000", "-ac", "1", str(path),
        )  # fmt: skip
    await asyncio.wait_for(
        mix_final(video, [AudioTrack(a1, 0.0), AudioTrack(a2, 1.4)], 3.0, out), timeout=30
    )
    assert abs(float(_probe(out)["format"]["duration"]) - 3.0) <= 0.1
    assert out.stat().st_size < 5_000_000


# ---- real ffmpeg: music tracks ------------------------------------------------------


def _decode(path: Path) -> tuple[np.ndarray, int]:
    """Stereo AAC/MP4 audio back to mono float samples."""
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-vn", "-f", "s16le", "-ac", "1",
         "-ar", "44100", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, dtype="<i2").astype(float) / 32768.0, 44100


def _band_db(samples: np.ndarray, rate: int, start: float, end: float, hz: float) -> float:
    """Level (dB) of one frequency inside a time window: keeps music and narration apart."""
    window = samples[int(start * rate) : int(end * rate)]
    window = window * np.hanning(len(window))
    spectrum = np.abs(np.fft.rfft(window)) / len(window)
    freqs = np.fft.rfftfreq(len(window), 1 / rate)
    peak = spectrum[(freqs > hz - 30) & (freqs < hz + 30)].max()
    return 20 * float(np.log10(max(peak, 1e-9)))


def _make_wav(path: Path, hz: int, seconds: float, amplitude: float) -> None:
    _ffmpeg(
        "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}:sample_rate=44100",
        "-af", f"volume={amplitude * 8}", "-ac", "2", str(path),  # lavfi sine peaks at 1/8
    )  # fmt: skip


@pytest.mark.slow
async def test_music_alone_fills_the_video_and_is_not_silent(tmp_path: Path) -> None:
    video, music, out = (tmp_path / n for n in ("v.mp4", "m.wav", "out.mp4"))
    _make_video(video, 6.0)
    _make_wav(music, 1000, 6.0, 0.3)
    await mix_final(video, [], 6.0, out, music=MusicMix(AudioTrack(music, 0.0)))
    info = _probe(out)
    assert [s["codec_name"] for s in info["streams"] if s["codec_type"] == "audio"] == ["aac"]
    assert abs(float(info["format"]["duration"]) - 6.0) <= 0.1
    samples, rate = _decode(out)
    assert _band_db(samples, rate, 1.0, 5.0, 1000) > -30  # the tone is there
    assert abs(samples[: int(0.001 * rate)]).max() < 0.03  # 15 ms fade-in: no click at t=0


@pytest.mark.slow
@pytest.mark.parametrize("music_seconds", [3.0, 9.0])
async def test_music_shorter_or_longer_than_the_video_still_pins_the_duration(
    tmp_path: Path, music_seconds: float
) -> None:
    video, music, out = (tmp_path / n for n in ("v.mp4", "m.wav", "out.mp4"))
    _make_video(video, 5.0)
    _make_wav(music, 500, music_seconds, 0.3)
    await asyncio.wait_for(
        mix_final(video, [], 5.0, out, music=MusicMix(AudioTrack(music, 0.0))), timeout=30
    )
    assert abs(float(_probe(out)["format"]["duration"]) - 5.0) <= 0.1


@pytest.mark.slow
async def test_music_is_ducked_while_the_narration_speaks_and_recovers_after(
    tmp_path: Path,
) -> None:
    """Narration 200 Hz at about -21 dBFS, 1.0-3.0 s and 5.0-7.0 s; music 2 kHz. The music's own
    frequency is measured in the mix: down >= 6 dB under speech, back within 2 dB of the free
    level 1 s after the speech stops. (Sweep behind these parameters: references/ffmpeg.md.)"""
    video, nar, music, out = (tmp_path / n for n in ("v.mp4", "n.wav", "m.wav", "out.mp4"))
    _make_video(video, 8.0)
    _make_wav(music, 2000, 8.0, 0.2)
    _make_wav(nar, 200, 2.0, 0.126)
    tracks = [AudioTrack(nar, 1.0, 2.0), AudioTrack(nar, 5.0, 2.0)]
    ducked = tmp_path / "ducked.mp4"
    await mix_final(
        video,
        tracks,
        8.0,
        ducked,
        music=MusicMix(AudioTrack(music, 0.0), duck_under_narration=True),
    )
    plain = tmp_path / "plain.mp4"
    await mix_final(
        video,
        tracks,
        8.0,
        plain,
        music=MusicMix(AudioTrack(music, 0.0), duck_under_narration=False),
    )
    d, rate = _decode(ducked)
    p, _ = _decode(plain)
    speech = (1.5, 2.8)
    after = (4.0, 4.9)  # >= 1 s after the first speech ended at 3.0 s
    drop = _band_db(d, rate, *speech, 2000) - _band_db(p, rate, *speech, 2000)
    back = _band_db(d, rate, *after, 2000) - _band_db(p, rate, *after, 2000)
    assert drop <= -6.0, drop
    assert back >= -2.0, back
    assert _band_db(d, rate, 1.5, 2.8, 200) == pytest.approx(
        _band_db(p, rate, 1.5, 2.8, 200), abs=1.5
    )


@pytest.mark.slow
async def test_a_broken_music_file_fails_without_leaving_output_or_touching_the_old_one(
    tmp_path: Path,
) -> None:
    video, out = tmp_path / "v.mp4", tmp_path / "out.mp4"
    _make_video(video, 2.0)
    out.write_bytes(b"old final")
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio at all")
    with pytest.raises(MixError):
        await mix_final(video, [], 2.0, out, music=MusicMix(AudioTrack(bad, 0.0)))
    assert out.read_bytes() == b"old final"
    assert not list(tmp_path.glob("*.tmp*"))


@pytest.mark.slow
async def test_the_bed_keeps_playing_after_the_last_narration_ends(tmp_path: Path) -> None:
    """The sidechain input (narration bus) ends with the last clip; without padding it the
    compressor's output ends there too and the bed is cut to silence for the rest of the film."""
    video, nar, music, out = (tmp_path / n for n in ("v.mp4", "n.wav", "m.wav", "out.mp4"))
    plain = tmp_path / "plain.mp4"
    _make_video(video, 8.0)
    _make_wav(music, 2000, 10.0, 0.2)  # longer than the video, so no fade-out is needed to see it
    _make_wav(nar, 200, 2.0, 0.126)
    tracks = [AudioTrack(nar, 1.0, 2.0)]
    await mix_final(
        video, tracks, 8.0, out, music=MusicMix(AudioTrack(music, 0.0), duck_under_narration=True)
    )
    await mix_final(
        video,
        tracks,
        8.0,
        plain,
        music=MusicMix(AudioTrack(music, 0.0), duck_under_narration=False),
    )
    ducked, rate = _decode(out)
    free, _ = _decode(plain)
    for window in ((4.0, 5.0), (6.0, 6.8)):
        gap = _band_db(ducked, rate, *window, 2000) - _band_db(free, rate, *window, 2000)
        assert gap >= -2.0, (window, gap)
