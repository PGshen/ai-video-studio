"""Free-form synthesis script for tests: no timeline, the script decides everything itself.

120 BPM, 8 bars (16 s): kicks on every beat, claps on beats 2 and 4, one riser sweep. It refuses
to run when `STUDIO_TIMELINE` is set, so a test that still injects the timeline fails loudly.
Only the standard library and NumPy, like a real agent script.
"""

import json
import os
import wave

import numpy as np

assert "STUDIO_TIMELINE" not in os.environ, "produce scripts get no timeline"

SR = 44100
BPM = 120.0
BARS = 8
beat = 60.0 / BPM
duration = BARS * 4 * beat
n = int(round(duration * SR))
out = np.zeros(n)
events = []


def add(start, body):
    i = int(round(start * SR))
    j = min(n, i + len(body))
    if i < n:
        out[i:j] += body[: j - i]


def kick():
    t = np.arange(int(0.18 * SR)) / SR
    body = np.sin(2 * np.pi * (55 + 90 * np.exp(-t * 35)) * t) * np.exp(-t * 14)
    body *= 0.5 * (1 + np.cos(np.pi * t / t[-1]))
    return 0.8 * body


def clap():
    t = np.arange(int(0.12 * SR)) / SR
    noise = np.random.default_rng(1).standard_normal(len(t))
    return 0.4 * noise * np.exp(-t * 30) * 0.5 * (1 + np.cos(np.pi * t / t[-1]))


for index in range(BARS * 4):
    at = index * beat
    if at >= duration - 0.2:
        continue
    add(at, kick())
    events.append({"name": "kick", "kind": "onset", "start": at, "end": at + 0.18})
    if index % 4 in (1, 3):
        add(at, clap())
        events.append({"name": "clap", "kind": "onset", "start": at, "end": at + 0.12})

rise = np.arange(int(2 * beat * 4 * SR)) / SR
sweep = 0.15 * np.sin(2 * np.pi * (200 + 600 * rise / rise[-1]) * rise) * (rise / rise[-1])
add(4 * beat * 2, sweep)
events.append({"name": "riser", "kind": "sweep", "start": 8 * beat, "end": 16 * beat})

peak = float(np.max(np.abs(out))) or 1.0
pcm = np.int16(out / peak * 0.7 * 32767)
with wave.open(os.environ["STUDIO_OUT_WAV"], "wb") as handle:
    handle.setnchannels(1)
    handle.setsampwidth(2)
    handle.setframerate(SR)
    handle.writeframes(pcm.tobytes())
with open(os.environ["STUDIO_OUT_EVENTS"], "w") as handle:
    document = {"duration": duration, "events": events}
    document["bpm"] = BPM
    json.dump(document, handle)
