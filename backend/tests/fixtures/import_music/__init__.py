"""Short song fixtures for the import-music stage tests (audio is generated, not committed)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from engines.audio_fixtures import SAMPLE_RATE, click_track
from fixtures.audio_engine import write_wav

BPM = 120.0
OFFSET = 0.5
SECONDS = 20.0


def write_click_song(path: Path, *, bpm: float = BPM, offset: float = OFFSET) -> Path:
    """A 20 s click track at `bpm` whose first (down)beat is at `offset`."""
    return write_wav(path, click_track(bpm, offset, SECONDS), SAMPLE_RATE)


def write_silence(path: Path, seconds: float = 10.0) -> Path:
    return write_wav(path, np.zeros(int(SAMPLE_RATE * seconds)), SAMPLE_RATE)
