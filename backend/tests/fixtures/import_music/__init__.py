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


def _shots(length: float) -> dict:
    """Three shots that cover `length` seconds: 25% / 50% / 25%."""
    first, second = round(length * 0.25, 3), round(length * 0.75, 3)
    return {
        "shots": [
            {"id": "intro", "label": "intro", "start": 0.0, "end": first},
            {"id": "verse", "label": "verse", "start": first, "end": second},
            {"id": "chorus", "label": "chorus", "start": second, "end": round(length, 3)},
        ]
    }


MV_SHOT_IDS = ("intro", "verse", "chorus")


def write_mv_workspace(
    workdir: Path,
    *,
    range_: tuple[float, float] | None = None,
) -> str:
    """Source song + hand-made `analysis.json` + shots (+ `range.json`) + trivial scenes.

    The song is `SECONDS` long; without `range_` the whole song is used. Returns the source hash.
    """
    import hashlib
    import json

    from fixtures.html_engine import projects as fx

    (workdir / "music").mkdir(exist_ok=True)
    song = write_click_song(workdir / "music" / "source.wav")
    digest = hashlib.sha256(song.read_bytes()).hexdigest()
    beats = [round(OFFSET + 0.5 * i, 3) for i in range(int((SECONDS - OFFSET) / 0.5))]
    (workdir / "music" / "analysis.json").write_text(
        json.dumps(
            {
                "source_hash": digest,
                "duration": SECONDS,
                "bpm": BPM,
                "offset": OFFSET,
                "residual_ms": 4.0,
                "confidence": 0.9,
                "beats": beats,
                "downbeats": beats[::4],
                "candidates": [],
                "hop": 0.1,
                "energy": [0.5] * int(SECONDS * 10),
                "warnings": [],
            }
        )
    )
    start, end = range_ if range_ is not None else (0.0, SECONDS)
    if range_ is not None:
        (workdir / "music" / "range.json").write_text(json.dumps({"start": start, "end": end}))
    (workdir / "animation").mkdir(exist_ok=True)
    (workdir / "animation" / "shots.json").write_text(json.dumps(_shots(end - start)))
    fx.write_project(workdir, scenes={sid: fx.PURE_SCENE_PLAIN for sid in MV_SHOT_IDS})
    return digest
