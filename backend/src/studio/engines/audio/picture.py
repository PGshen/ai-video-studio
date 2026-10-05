"""分析图（子项目 3 设计 §7.3）：波形、对数频率谱图、能量与起音三行，叠加段落边界、小节线与拍线、
事件标记。
用 NumPy 算谱图、Pillow 绘制，不依赖 matplotlib；文字只用 ASCII（Pillow 默认字体没有汉字）。
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from studio.engines.audio.analysis import MusicReport
from studio.engines.audio.song import SongAnalysis
from studio.engines.audio.wav import Samples

WIDTH, HEIGHT = 1800, 1000
_LEFT, _RIGHT = 70, 20
_PANELS = {"wave": (30, 250), "spec": (270, 790), "energy": (810, 950)}
_FFT = 2048
_DB_FLOOR = 70.0
_MIN_HZ, _MAX_HZ = 30.0, 16000.0
_PALETTE = [
    (230, 60, 60),
    (60, 170, 80),
    (60, 130, 255),
    (200, 60, 200),
    (255, 170, 0),
    (0, 200, 200),
    (150, 150, 150),
    (150, 100, 50),
]
_STOPS = [
    (0.0, (0, 0, 4)),
    (0.25, (60, 15, 110)),
    (0.5, (170, 50, 100)),
    (0.75, (245, 130, 40)),
    (1.0, (252, 250, 160)),
]
_LUT = np.array(
    [
        [np.interp(v / 255.0, [s[0] for s in _STOPS], [s[1][c] for s in _STOPS]) for c in range(3)]
        for v in range(256)
    ],
    dtype=np.uint8,
)


def _ascii(text: str) -> str:
    return "".join(ch if ord(ch) < 128 else "?" for ch in text)


def _spectrogram(mono: np.ndarray, sample_rate: int, cols: int, rows: int) -> np.ndarray:
    if len(mono) < _FFT:
        mono = np.pad(mono, (0, _FFT - len(mono)))
    window = np.hanning(_FFT)
    starts = np.linspace(0, len(mono) - _FFT, cols).astype(int)
    index = starts[:, None] + np.arange(_FFT)[None, :]
    magnitude = np.abs(np.fft.rfft(mono[index] * window, axis=1))  # (cols, bins)
    top = min(_MAX_HZ, sample_rate / 2)
    freqs = np.geomspace(_MIN_HZ, top, rows)
    bins = np.clip(np.round(freqs * _FFT / sample_rate).astype(int), 0, magnitude.shape[1] - 1)
    db = 20.0 * np.log10(magnitude[:, bins].T + 1e-9)  # (rows, cols), low frequency first
    level = np.clip((db - db.max() + _DB_FLOOR) / _DB_FLOOR, 0.0, 1.0)
    return _LUT[(level * 255).astype(np.uint8)][::-1]  # low frequencies at the bottom


def _waveform_columns(mono: np.ndarray, cols: int) -> tuple[np.ndarray, np.ndarray]:
    if len(mono) == 0:
        return np.zeros(cols), np.zeros(cols)
    edges = np.linspace(0, len(mono), cols + 1).astype(int)
    edges = np.minimum(edges[:-1], len(mono) - 1)
    return np.minimum.reduceat(mono, edges), np.maximum.reduceat(mono, edges)


def render_analysis_png(
    report: MusicReport,
    timeline: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    samples: Samples,
) -> bytes:
    mono = samples.mono()
    duration = float(timeline.get("duration") or samples.duration) or 1.0
    plot_w = WIDTH - _LEFT - _RIGHT
    image = Image.new("RGB", (WIDTH, HEIGHT), (250, 250, 250))
    draw = ImageDraw.Draw(image)

    def x_of(t: float) -> float:
        return _LEFT + max(0.0, min(1.0, t / duration)) * plot_w

    # waveform
    top, bottom = _PANELS["wave"]
    mid, half = (top + bottom) / 2, (bottom - top) / 2
    draw.rectangle(
        [_LEFT, top, _LEFT + plot_w, bottom], fill=(255, 255, 255), outline=(180, 180, 180)
    )
    low, high = _waveform_columns(mono, plot_w)
    for column in range(plot_w):
        draw.line(
            [
                (_LEFT + column, mid - high[column] * half),
                (_LEFT + column, mid - low[column] * half),
            ],
            fill=(40, 40, 40),
        )
    draw.text((6, top + 4), "waveform", fill=(0, 0, 0))

    # spectrogram
    top, bottom = _PANELS["spec"]
    spectrogram = _spectrogram(mono, samples.sample_rate, plot_w, bottom - top)
    image.paste(Image.fromarray(spectrogram, "RGB"), (_LEFT, top))
    draw.text((6, top + 4), "spectrogram", fill=(0, 0, 0))
    nyquist = min(_MAX_HZ, samples.sample_rate / 2)
    for hz in (100, 1000, 10000):
        if hz < nyquist:
            frac = np.log(hz / _MIN_HZ) / np.log(nyquist / _MIN_HZ)
            y = bottom - frac * (bottom - top)
            draw.line([(_LEFT - 6, y), (_LEFT, y)], fill=(0, 0, 0))
            draw.text((6, y - 6), f"{hz} Hz", fill=(0, 0, 0))

    # energy + onsets
    top, bottom = _PANELS["energy"]
    draw.rectangle(
        [_LEFT, top, _LEFT + plot_w, bottom], fill=(255, 255, 255), outline=(180, 180, 180)
    )
    points = [
        (x_of(i * report.energy_hop), bottom - 4 - value * (bottom - top - 8))
        for i, value in enumerate(report.energy)
    ]
    if len(points) >= 2:
        draw.line(points, fill=(0, 140, 90), width=2)
    for t in report.onsets:
        x = x_of(t)
        draw.polygon([(x - 3, top + 2), (x + 3, top + 2), (x, top + 9)], fill=(200, 0, 0))
    draw.text((6, top + 4), "energy 0-1", fill=(0, 0, 0))
    draw.text((6, top + 20), "red = detected", fill=(200, 0, 0))

    # overlays on every panel
    grid = timeline.get("grid")
    for panel_top, panel_bottom in _PANELS.values():
        if grid:
            for t in grid.get("beats", []):
                draw.line([(x_of(t), panel_top), (x_of(t), panel_bottom)], fill=(150, 190, 255))
            for t in grid.get("downbeats", []):
                draw.line(
                    [(x_of(t), panel_top), (x_of(t), panel_bottom)], fill=(40, 100, 230), width=2
                )
        for section in timeline.get("sections", []):
            x = x_of(float(section["start"]))
            draw.line([(x, panel_top), (x, panel_bottom)], fill=(255, 140, 0), width=3)
    for section in timeline.get("sections", []):
        draw.text(
            (x_of(float(section["start"])) + 4, _PANELS["wave"][0] + 4),
            _ascii(str(section["id"])),
            fill=(200, 100, 0),
        )

    # event markers (top strip of the spectrogram) and legend
    names = list(dict.fromkeys(str(e.get("name", "")) for e in events))
    colour_of = {name: _PALETTE[i % len(_PALETTE)] for i, name in enumerate(names)}
    strip_top = _PANELS["spec"][0]
    for event in events:
        colour = colour_of[str(event.get("name", ""))]
        x = x_of(float(event.get("start", 0.0)))
        if event.get("kind") == "sweep":
            draw.line(
                [(x, strip_top + 6), (x_of(float(event.get("end", 0.0))), strip_top + 6)],
                fill=colour,
                width=4,
            )
        else:
            draw.polygon([(x - 4, strip_top), (x + 4, strip_top), (x, strip_top + 9)], fill=colour)
    for i, name in enumerate(names[: len(_PALETTE)]):
        lx = WIDTH - _RIGHT - 130 * (len(names[: len(_PALETTE)]) - i)
        draw.rectangle([lx, 8, lx + 10, 18], fill=colour_of[name])
        draw.text((lx + 14, 7), _ascii(name)[:12], fill=(0, 0, 0))

    # time axis
    step = 1.0 if duration <= 40 else 5.0
    t = 0.0
    while t <= duration + 1e-9:
        x = x_of(t)
        draw.line([(x, _PANELS["energy"][1]), (x, _PANELS["energy"][1] + 6)], fill=(0, 0, 0))
        draw.text((x - 6, _PANELS["energy"][1] + 8), f"{t:g}s", fill=(0, 0, 0))
        t += step
    draw.text((6, HEIGHT - 20), "orange = sections, blue = bars/beats", fill=(0, 0, 0))

    return _encode(image)


def _encode(image: Image.Image) -> bytes:
    # 256-colour palette: the spectrogram is a smooth colour map, and a truecolour PNG of noisy
    # audio is ~0.9 MB (too big for the agent to open with Read, SDK limit 1 MiB per message).
    buffer = io.BytesIO()
    image.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
        buffer, format="PNG", optimize=True
    )
    return buffer.getvalue()


_MIN_LINE_GAP_PX = 3.0
"""Beat lines closer than this are skipped (a 600 s song would turn into a solid block)."""


def render_song_png(analysis: SongAnalysis, samples: Samples) -> bytes:
    """Analysis picture of an imported song: waveform, spectrogram, energy; thin beat lines, thick
    downbeat lines, orange candidate boundaries."""
    mono = samples.mono()
    duration = analysis.duration or samples.duration or 1.0
    plot_w = WIDTH - _LEFT - _RIGHT
    image = Image.new("RGB", (WIDTH, HEIGHT), (250, 250, 250))
    draw = ImageDraw.Draw(image)

    def x_of(t: float) -> float:
        return _LEFT + max(0.0, min(1.0, t / duration)) * plot_w

    top, bottom = _PANELS["wave"]
    mid, half = (top + bottom) / 2, (bottom - top) / 2
    draw.rectangle(
        [_LEFT, top, _LEFT + plot_w, bottom], fill=(255, 255, 255), outline=(180, 180, 180)
    )
    low, high = _waveform_columns(mono, plot_w)
    for column in range(plot_w):
        draw.line(
            [
                (_LEFT + column, mid - high[column] * half),
                (_LEFT + column, mid - low[column] * half),
            ],
            fill=(40, 40, 40),
        )
    draw.text((6, top + 4), "waveform", fill=(0, 0, 0))

    top, bottom = _PANELS["spec"]
    image.paste(
        Image.fromarray(_spectrogram(mono, samples.sample_rate, plot_w, bottom - top), "RGB"),
        (_LEFT, top),
    )
    draw.text((6, top + 4), "spectrogram", fill=(0, 0, 0))

    top, bottom = _PANELS["energy"]
    draw.rectangle(
        [_LEFT, top, _LEFT + plot_w, bottom], fill=(255, 255, 255), outline=(180, 180, 180)
    )
    points = [
        (x_of(i * analysis.hop), bottom - 4 - value * (bottom - top - 8))
        for i, value in enumerate(analysis.energy)
    ]
    if len(points) >= 2:
        draw.line(points, fill=(0, 140, 90), width=2)
    draw.text((6, top + 4), "energy 0-1", fill=(0, 0, 0))

    beat_gap = (x_of(analysis.beats[1]) - x_of(analysis.beats[0])) if len(analysis.beats) > 1 else 0
    for panel_top, panel_bottom in _PANELS.values():
        if beat_gap >= _MIN_LINE_GAP_PX:
            for t in analysis.beats:
                draw.line([(x_of(t), panel_top), (x_of(t), panel_bottom)], fill=(150, 190, 255))
        for t in analysis.downbeats:
            draw.line([(x_of(t), panel_top), (x_of(t), panel_bottom)], fill=(40, 100, 230), width=2)
        for t in analysis.candidates:
            draw.line([(x_of(t), panel_top), (x_of(t), panel_bottom)], fill=(255, 140, 0), width=3)
    for t in analysis.candidates:
        draw.text((x_of(t) + 4, _PANELS["wave"][0] + 4), f"{t:.1f}s", fill=(200, 100, 0))

    step = 5.0 if duration <= 120 else 30.0
    t = 0.0
    while t <= duration + 1e-9:
        x = x_of(t)
        draw.line([(x, _PANELS["energy"][1]), (x, _PANELS["energy"][1] + 6)], fill=(0, 0, 0))
        draw.text((x - 6, _PANELS["energy"][1] + 8), f"{t:g}s", fill=(0, 0, 0))
        t += step
    draw.text(
        (6, HEIGHT - 20),
        f"bpm {analysis.bpm:.1f}  confidence {analysis.confidence:.2f}  "
        "orange = candidate boundaries, thick blue = downbeats, thin blue = beats",
        fill=(0, 0, 0),
    )
    return _encode(image)
