"""`engines.audio.picture`：分析图（子项目 3 设计 §7.3）。只验证形状与稳健性，不比像素。"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from fixtures.audio_engine import SR, kick_events, kick_train, reel_timeline
from studio.engines.audio.analysis import analyze
from studio.engines.audio.picture import render_analysis_png
from studio.engines.audio.wav import Samples

BPM = 128.0


def _render(data: np.ndarray, timeline: dict, events: list[dict]) -> Image.Image:
    samples = Samples(data=data, sample_rate=SR)
    report = analyze(samples, timeline, events)
    png = render_analysis_png(report, timeline, events, samples)
    image = Image.open(io.BytesIO(png))
    image.load()
    return image


def test_picture_is_a_png_of_fixed_size_with_content() -> None:
    timeline = reel_timeline(BPM, 4, sections=2)
    image = _render(kick_train(BPM, 4), timeline, kick_events(BPM, 4))
    assert image.format == "PNG"
    assert image.size == (1800, 1000)
    colours = image.convert("RGB").getcolors(maxcolors=1_000_000)
    assert (
        colours is not None and len(colours) > 50
    )  # waveform, spectrogram, markers: not a blank page


def test_picture_survives_many_events_non_ascii_names_and_no_events() -> None:
    timeline = reel_timeline(BPM, 2)
    many = [
        {
            "name": f"事件{i % 12}",
            "kind": "onset" if i % 3 else "sweep",
            "start": i * 0.01,
            "end": i * 0.01 + 0.05,
        }
        for i in range(300)
    ]
    for events in (many, []):
        image = _render(kick_train(BPM, 2), timeline, events)
        assert image.size == (1800, 1000)


def test_picture_survives_silence_and_very_short_audio() -> None:
    timeline = reel_timeline(BPM, 2)
    assert _render(np.zeros(int(timeline["duration"] * SR)), timeline, []).size == (1800, 1000)
    short = {**timeline, "duration": 0.05, "sections": []}
    assert _render(np.full(int(0.05 * SR), 0.1), short, []).size == (1800, 1000)


def test_picture_works_without_a_grid() -> None:
    timeline = {**reel_timeline(BPM, 2), "grid": None}
    assert _render(kick_train(BPM, 2), timeline, []).size == (1800, 1000)


def test_even_a_noisy_picture_stays_small_enough_to_be_read_by_the_agent() -> None:
    """The agent may open `analysis.png` with the built-in Read: its base64 must stay under the
    SDK's 1 MiB message limit (a 12 s white-noise track used to give ~0.9 MB of PNG)."""
    timeline = reel_timeline(BPM, 6)
    noise = np.random.default_rng(1).normal(0, 0.2, int(timeline["duration"] * SR))
    samples = Samples(data=noise, sample_rate=SR)
    png = render_analysis_png(analyze(samples, timeline, []), timeline, [], samples)
    assert len(png) <= 600_000
    assert Image.open(io.BytesIO(png)).size == (1800, 1000)


def test_song_picture_is_a_png_of_fixed_size_with_content() -> None:
    from engines.audio_fixtures import SAMPLE_RATE, click_track
    from studio.engines.audio.picture import render_song_png
    from studio.engines.audio.song import analyze_samples

    samples = Samples(data=click_track(120.0, 0.5, 12.0), sample_rate=SAMPLE_RATE)
    analysis = analyze_samples(samples, source_hash="0" * 64)
    image = Image.open(io.BytesIO(render_song_png(analysis, samples)))
    image.load()
    assert image.format == "PNG"
    assert image.size == (1800, 1000)
    colours = image.convert("RGB").getcolors(maxcolors=1_000_000)
    assert colours is not None and len(colours) > 50


def test_song_picture_survives_a_long_song_without_candidates() -> None:
    from studio.engines.audio.picture import render_song_png
    from studio.engines.audio.song import SongAnalysis

    seconds = 600
    samples = Samples(data=np.full(seconds * SR, 0.1), sample_rate=SR)
    analysis = SongAnalysis(
        source_hash="0" * 64, duration=float(seconds), bpm=240.0, offset=0.0, residual_ms=1.0,
        confidence=1.0, beats=[i * 0.25 for i in range(seconds * 4)],
        downbeats=[i * 1.0 for i in range(seconds)], candidates=[], hop=0.05,
        energy=[0.5] * (seconds * 20),
    )  # fmt: skip
    image = Image.open(io.BytesIO(render_song_png(analysis, samples)))
    assert image.size == (1800, 1000)
