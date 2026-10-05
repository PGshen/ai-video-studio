"""Reference synthesis script for tests: derives every time from the timeline, so retiming works.

Reel: kicks on every grid beat, claps on beats 2 and 4 from bar 2, one riser sweep in bar 2,
louder in later sections. Narration bed: a declared 100 BPM / 0.1 s offset grid of soft kicks.
Only the standard library and NumPy, like a real agent script.
"""

import json
import os
import wave

import numpy as np

SR = 44100
timeline = json.load(open(os.environ["STUDIO_TIMELINE"]))
duration = timeline["duration"]
n = int(round(duration * SR))
out = np.zeros(n)
events = []
grid = timeline.get("grid")
if grid:
    bpm, offset = float(grid["bpm"]), float(grid["offset"])
    beats = [b for b in grid["beats"] if b < duration - 0.2]
else:
    bpm, offset = 100.0, 0.1
    beats = [offset + i * 60.0 / bpm for i in range(int((duration - offset) / (60.0 / bpm)))]
    beats = [b for b in beats if b < duration - 0.2]
beat = 60.0 / bpm
sections = timeline["sections"]


def gain_at(t):
    for index, section in enumerate(sections):
        if section["start"] <= t < section["end"]:
            return 0.35 + 0.65 * index / max(1, len(sections) - 1)
    return 0.35


def add(start, body):
    i = int(round(start * SR))
    j = min(n, i + len(body))
    if i < n:
        out[i:j] += body[: j - i]


def kick(gain):
    t = np.arange(int(0.18 * SR)) / SR
    body = np.sin(2 * np.pi * (55 + 90 * np.exp(-t * 35)) * t) * np.exp(-t * 14)
    body *= 0.5 * (1 + np.cos(np.pi * t / t[-1]))  # smooth tail: a hard cut reads as a 2nd onset
    return gain * 0.8 * body


for index, start in enumerate(beats):
    add(start, kick(gain_at(start)))
    events.append({"name": "kick", "kind": "onset", "start": start, "end": start + 0.18})
    if grid and index % 4 in (1, 3) and index >= 4:
        t = np.arange(int(0.1 * SR)) / SR
        clap = np.random.default_rng(index).standard_normal(len(t)) * np.exp(-t * 40) * 0.3
        add(start, clap * gain_at(start))
        events.append({"name": "clap", "kind": "onset", "start": start, "end": start + 0.1})
if grid and len(beats) > 8:
    lo, hi = beats[4], beats[8]
    events.append({"name": "riser", "kind": "sweep", "start": lo, "end": hi})
    t = np.arange(int((hi - lo) * SR)) / SR
    add(lo, 0.15 * np.sin(2 * np.pi * (400 + 2000 * t / t[-1]) * t))

peak = float(np.max(np.abs(out))) or 1.0
out = out / peak * 0.89
wav = wave.open(os.environ["STUDIO_OUT_WAV"], "wb")
wav.setnchannels(1)
wav.setsampwidth(2)
wav.setframerate(SR)
wav.writeframes((np.clip(out, -1, 1) * 32767).astype("<i2").tobytes())
wav.close()
doc = {"bpm": bpm, "duration": duration, "events": events}
if not grid:
    doc["offset"] = offset
json.dump(doc, open(os.environ["STUDIO_OUT_EVENTS"], "w"))
