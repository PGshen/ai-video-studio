"""A script that ignores the timeline (fixed 128 BPM, 11.25 s): the retiming check must catch it."""

import json
import os
import wave

import numpy as np

SR = 44100
bpm, duration = 128.0, 11.25
out = np.zeros(int(duration * SR))
events = []
for i in range(int(duration / (60 / bpm))):
    start = i * 60 / bpm
    t = np.arange(int(0.18 * SR)) / SR
    body = 0.8 * np.sin(2 * np.pi * (55 + 90 * np.exp(-t * 35)) * t) * np.exp(-t * 14)
    j = int(start * SR)
    out[j : j + len(body)] += body[: len(out) - j]
    events.append({"name": "kick", "kind": "onset", "start": start, "end": start + 0.18})
wav = wave.open(os.environ["STUDIO_OUT_WAV"], "wb")
wav.setnchannels(1)
wav.setsampwidth(2)
wav.setframerate(SR)
wav.writeframes((np.clip(out, -1, 1) * 32767).astype("<i2").tobytes())
wav.close()
json.dump(
    {"bpm": bpm, "duration": duration, "events": events}, open(os.environ["STUDIO_OUT_EVENTS"], "w")
)
