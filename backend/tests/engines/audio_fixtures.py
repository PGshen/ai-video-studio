"""Synthetic audio for song-analysis tests: a click track with known BPM and offset.

Shared by the song, runner and stage tests. Deterministic: same arguments, same samples.
"""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 22050


def click_track(
    bpm: float,
    offset: float,
    seconds: float,
    sr: int = SAMPLE_RATE,
    *,
    beats_per_bar: int = 4,
    jitter: float = 0.0,
    seed: int = 0,
) -> np.ndarray:
    """Mono float64 track: a decaying noise burst plus a low kick on every beat.

    The first beat is at `offset`; every `beats_per_bar`-th beat (the downbeats) is louder.
    `jitter` (seconds, std) displaces each beat randomly to emulate loose playing.
    """
    rng = np.random.default_rng(seed)
    total = int(round(seconds * sr))
    out = np.zeros(total)
    burst_len = int(0.06 * sr)
    kick_len = int(0.12 * sr)
    burst_t = np.arange(burst_len) / sr
    kick_t = np.arange(kick_len) / sr
    kick = np.sin(2 * np.pi * 60.0 * kick_t) * np.exp(-kick_t / 0.05)
    period = 60.0 / bpm
    index = 0
    while True:
        moment = offset + index * period
        if jitter:
            moment += float(rng.normal(0.0, jitter))
        start = int(round(moment * sr))
        if start >= total:
            break
        gain = 1.0 if index % beats_per_bar == 0 else 0.6
        noise = rng.standard_normal(burst_len) * np.exp(-burst_t / 0.012)
        burst = 0.35 * gain * noise
        end = min(total, start + max(burst_len, kick_len))
        if start >= 0:
            piece = np.zeros(max(burst_len, kick_len))
            piece[:burst_len] += burst
            piece[:kick_len] += 0.6 * gain * kick
            out[start:end] += piece[: end - start]
        index += 1
    peak = float(np.max(np.abs(out)))
    return out / peak * 0.8 if peak > 0 else out


def click_times(
    times: list[float],
    seconds: float,
    sr: int = SAMPLE_RATE,
    *,
    gains: list[float] | None = None,
) -> np.ndarray:
    """Mono float64 track with one click (noise burst + low kick) at each given time."""
    total = int(round(seconds * sr))
    out = np.zeros(total)
    rng = np.random.default_rng(0)
    burst_len = int(0.06 * sr)
    kick_len = int(0.12 * sr)
    burst_t = np.arange(burst_len) / sr
    kick_t = np.arange(kick_len) / sr
    kick = np.sin(2 * np.pi * 60.0 * kick_t) * np.exp(-kick_t / 0.05)
    for i, moment in enumerate(times):
        start = int(round(moment * sr))
        if start < 0 or start >= total:
            continue
        gain = 1.0 if gains is None else gains[i]
        piece = np.zeros(kick_len)
        piece[:burst_len] += 0.35 * gain * rng.standard_normal(burst_len) * np.exp(-burst_t / 0.012)
        piece += 0.6 * gain * kick
        end = min(total, start + kick_len)
        out[start:end] += piece[: end - start]
    peak = float(np.max(np.abs(out)))
    return out / peak * 0.8 if peak > 0 else out
