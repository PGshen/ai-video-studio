"""`engines.audio` 测试用的合成音频与时间轴（现场生成，不入库二进制）。"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np

SR = 44100


def kick_train(
    bpm: float, bars: int, *, sr: int = SR, shift: float = 0.0, skip: set[int] | None = None
) -> np.ndarray:
    """Mono kick on every beat (sine with a fast pitch drop), `shift` seconds late."""
    beat = 60.0 / bpm
    total = int(bars * 4 * beat * sr)
    out = np.zeros(total)
    for index in range(bars * 4):
        if skip and index in skip:
            continue
        start = int((index * beat + shift) * sr)
        length = min(int(0.18 * sr), total - start)
        if length <= 0:
            continue
        t = np.arange(length) / sr
        out[start : start + length] += (
            0.8 * np.sin(2 * np.pi * (55 + 90 * np.exp(-t * 35)) * t) * np.exp(-t * 14)
        )
    return out


def reel_timeline(bpm: float = 128.0, bars: int = 2, *, sections: int = 1) -> dict[str, Any]:
    beat = 60.0 / bpm
    duration = bars * 4 * beat
    per = duration / sections
    return {
        "duration": duration,
        "grid": {
            "bpm": bpm,
            "offset": 0.0,
            "beats": [i * beat for i in range(bars * 4 + 1)],
            "downbeats": [i * 4 * beat for i in range(bars + 1)],
        },
        "sections": [
            {"id": f"s{i + 1}", "label": f"S{i + 1}", "start": i * per, "end": (i + 1) * per}
            for i in range(sections)
        ],
        "narration": [],
        "moments": [],
        "music": None,
        "lyrics": [],
    }


def kick_events(bpm: float, bars: int, *, skip: set[int] | None = None) -> list[dict[str, Any]]:
    beat = 60.0 / bpm
    return [
        {"name": "kick", "kind": "onset", "start": i * beat, "end": i * beat + 0.18}
        for i in range(bars * 4)
        if not (skip and i in skip)
    ]


def write_wav(path: Path, data: np.ndarray, sr: int = SR, *, kind: str = "pcm16") -> Path:
    """Minimal RIFF writer: pcm16 / pcm24 / pcm32 / float32; mono or stereo."""
    channels = 1 if data.ndim == 1 else data.shape[1]
    clipped = np.clip(data, -1.0, 1.0)
    if kind == "pcm16":
        payload, fmt_tag, bits = (clipped * 32767).astype("<i2").tobytes(), 1, 16
    elif kind == "pcm32":
        payload, fmt_tag, bits = (clipped * 2147483647).astype("<i4").tobytes(), 1, 32
    elif kind == "pcm24":
        ints = (clipped * 8388607).astype("<i4").reshape(-1)
        payload = b"".join(struct.pack("<i", int(v))[:3] for v in ints)
        fmt_tag, bits = 1, 24
    elif kind == "float32":
        payload, fmt_tag, bits = clipped.astype("<f4").tobytes(), 3, 32
    else:  # pragma: no cover - test helper misuse
        raise ValueError(kind)
    block = channels * bits // 8
    fmt = struct.pack("<HHIIHH", fmt_tag, channels, sr, sr * block, block, bits)
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(payload))
        + payload
    )
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path
