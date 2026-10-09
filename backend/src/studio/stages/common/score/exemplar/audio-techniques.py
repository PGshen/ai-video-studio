"""Synthesis techniques, from a finished 15 s reel soundtrack. A reference, not an API.

Everything is plain NumPy: oscillators, filters, envelopes, FFT-convolution reverb. The
arrangement at the bottom shows the contract: read the timeline, place every sound on the grid it
gives you, write the WAV and the named events. Two traps cost the most iterations in practice:
- end every sound with a smooth fade; a hard cut is a click, read as a second onset;
- derive every time from the timeline (never write a literal second): `render_music` reruns the
  script with another BPM and total length and rejects scripts that do not follow.
"""

import json
import os
import wave

import numpy as np

SR = 44100
rng = np.random.default_rng(7)  # seeded: same output every run


def tt(d):
    return np.arange(int(d * SR)) / SR


def noise(d):
    return rng.uniform(-1, 1, int(d * SR))


def onepole_lp(x, fc):
    """Time-varying one-pole low-pass; `fc` is a scalar or an array in Hz."""
    fc = np.broadcast_to(np.asarray(fc, float), x.shape)
    a = 1 - np.exp(-2 * np.pi * fc / SR)
    y = np.empty_like(x)
    s = 0.0
    for i in range(len(x)):
        s += a[i] * (x[i] - s)
        y[i] = s
    return y


def hp(x, fc):
    return x - onepole_lp(x, fc)


def svf_bp(x, fc, q=2.0):
    """State-variable band-pass; sweep `fc` over time for risers and whooshes."""
    fc = np.broadcast_to(np.asarray(fc, float), x.shape)
    f = 2 * np.sin(np.pi * np.minimum(fc, SR / 6) / SR)
    lo = bp = 0.0
    y = np.empty_like(x)
    for i in range(len(x)):
        hi = x[i] - lo - (1 / q) * bp
        bp += f[i] * hi
        lo += f[i] * bp
        y[i] = bp
    return y


def smooth_tail(x, ms=40):
    n = min(len(x), int(ms / 1000 * SR))
    x[-n:] *= 0.5 * (1 + np.cos(np.linspace(0, np.pi, n)))
    return x


# ---------- instruments ----------
def kick(d=0.4, low=46):
    """Sine with a fast downward pitch sweep (the thump) plus a short noise click."""
    t = tt(d)
    f = low + 120 * np.exp(-t * 32) + 30 * np.exp(-t * 6)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 6.5)
    s[:150] += noise(150 / SR) * np.linspace(0.6, 0, 150)
    return smooth_tail(np.tanh(s * 1.8) * 0.9)


def clap():
    """Band-passed noise with three quick re-attacks, then a longer tail."""
    d = 0.3
    t = tt(d)
    env = np.zeros_like(t)
    for k, offset in enumerate([0, 0.011, 0.022]):
        m = t >= offset
        env[m] += np.exp(-(t[m] - offset) * (140 if k < 2 else 16))
    return smooth_tail(svf_bp(noise(d), 1400, 1.2) * env * 1.3)


def hat(open_=False):
    d = 0.3 if open_ else 0.06
    return smooth_tail(hp(hp(noise(d), 7000), 7000) * np.exp(-tt(d) * (14 if open_ else 70)) * 0.9)


def bass(freq, d, cut=900, drive=2.0):
    """Two slightly detuned saws plus a sub sine, low-passed, saturated, filter closing."""
    t = tt(d)
    saw = 2 * ((freq * t) % 1) - 1
    saw2 = 2 * ((freq * 1.007 * t) % 1) - 1
    sub = np.sin(2 * np.pi * freq / 2 * t)
    env = np.minimum(1, t / 0.004) * np.exp(-t * 3) * np.minimum(1, (d - t) / 0.02)
    fc = cut * (0.35 + 1.4 * np.exp(-t * 14))
    s = onepole_lp(onepole_lp((saw + saw2) * 0.5, fc), fc)
    return np.tanh((s * 0.9 + sub * 0.7) * drive) * env * 0.55


def riser(d, f0=300, f1=6000):
    """Band-passed noise whose centre frequency and level climb: tension before a hit."""
    t = tt(d)
    p = t / d
    n = svf_bp(noise(d), f0 * (f1 / f0) ** (p**1.6), 3.0)
    tone = np.sin(2 * np.pi * np.cumsum(110 * 2 ** (p * 3)) / SR) * 0.25
    return smooth_tail((n * 1.4 + tone) * p**2)


def impact(d=1.6):
    """Low boom with a falling pitch, a noise crash and a muffled thud."""
    t = tt(d)
    boom = np.sin(2 * np.pi * np.cumsum(30 + 90 * np.exp(-t * 18)) / SR) * np.exp(-t * 2.2)
    crash = hp(noise(d), 1800) * np.exp(-t * 3.5) * 0.45
    thud = onepole_lp(noise(d), 300) * np.exp(-t * 9) * 2.5
    return smooth_tail(np.tanh((boom * 1.4 + crash + thud) * 1.5) * 0.9, 120)


def convolve(x, h):
    """FFT convolution: a decaying-noise impulse response is a perfectly good reverb."""
    n = 1 << (len(x) + len(h) - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(h, n), n)[: len(x)]


# ---------- arrangement: every time comes from the timeline ----------
timeline = json.load(open(os.environ["STUDIO_TIMELINE"], encoding="utf-8"))
duration = timeline["duration"]
N = int(round(duration * SR))
out = np.zeros(N)
send = np.zeros(N)  # reverb send
events = []


def place(sig, t, gain=1.0, verb=0.0):
    i = int(round(t * SR))
    if 0 <= i < N:
        part = sig[: N - i] * gain
        out[i : i + len(part)] += part
        send[i : i + len(part)] += part * verb


def event(name, kind, start, end):
    events.append({"name": name, "kind": kind, "start": float(start), "end": float(end)})


grid = timeline.get("grid")
if grid:  # reel: the beat grid comes from the beat sheet
    bpm, offset = float(grid["bpm"]), float(grid["offset"])
else:  # narration bed: choose your own tempo and declare it
    bpm, offset = 96.0, 0.0
beat = 60.0 / bpm
K, C, H = kick(), clap(), hat()
count = int((duration - offset) / beat)
for i in range(count):
    t = offset + i * beat
    place(K, t, 0.9)
    event("kick", "onset", t, t + 0.18)
    if i % 4 in (1, 3):  # claps on beats 2 and 4
        place(C, t, 0.6, verb=0.3)
        event("clap", "onset", t, t + 0.12)
    place(H, t + beat / 2, 0.3)  # off-beat hat
    event("hat", "onset", t + beat / 2, t + beat / 2 + 0.06)
    if i % 4 == 0:
        place(bass(55.0, beat * 0.9, 700), t, 0.8)
        event("bass", "onset", t, t + beat * 0.9)
if count >= 8:  # a riser into the second half
    start, length = offset + (count - 4) * beat, 4 * beat - 0.2
    place(riser(length), start, 0.5)
    event("riser", "sweep", start, start + length)
    place(impact(), start + 4 * beat, 0.9, verb=0.4)
    event("impact", "onset", start + 4 * beat, start + 4 * beat + 0.2)

# reverb: decaying-noise impulse response
ir = rng.standard_normal(int(0.9 * SR)) * np.exp(-tt(0.9) * 5)
out += convolve(send, onepole_lp(ir, 5000)) * 0.08
out = np.tanh(out * 0.9)  # glue / soft limiter
out = out / (np.max(np.abs(out)) or 1.0) * 0.89  # about -1 dBFS peak
fade = int(0.01 * SR)
out[:fade] *= np.linspace(0, 1, fade)
out[-fade:] *= np.linspace(1, 0, fade)

wav = wave.open(os.environ["STUDIO_OUT_WAV"], "wb")
wav.setnchannels(1)
wav.setsampwidth(2)
wav.setframerate(SR)
wav.writeframes((np.clip(out, -1, 1) * 32767).astype("<i2").tobytes())
wav.close()
doc = {"bpm": bpm, "duration": duration, "events": events}
if not grid:
    doc["offset"] = offset  # the declared grid of a narration project
json.dump(doc, open(os.environ["STUDIO_OUT_EVENTS"], "w", encoding="utf-8"))
