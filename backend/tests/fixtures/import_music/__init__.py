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


MV_SECTIONS = [
    {"id": "intro", "label": "intro", "start": 0.5, "end": 4.5},
    {"id": "verse", "label": "verse", "start": 4.5, "end": 12.5},
    {"id": "chorus", "label": "chorus", "start": 12.5, "end": 18.5},
]


def write_mv_workspace(
    workdir: Path,
    *,
    range_: tuple[float, float] | None = None,
    refs: tuple[str, ...] | None = None,
) -> str:
    """Source song + hand-made `analysis.json`/`sections.json` + beatsheet + trivial scenes.

    Returns the source hash. With `range_`, `refs` must list the sections inside it.
    """
    import hashlib
    import json

    from fixtures.html_engine import projects as fx

    (workdir / "music").mkdir(exist_ok=True)
    (workdir / "beatsheet").mkdir(exist_ok=True)
    song = write_click_song(workdir / "music" / "source.wav")
    digest = hashlib.sha256(song.read_bytes()).hexdigest()
    (workdir / "music" / "analysis.json").write_text(
        json.dumps(
            {
                "source_hash": digest,
                "duration": SECONDS,
                "bpm": BPM,
                "offset": OFFSET,
                "residual_ms": 4.0,
                "confidence": 0.9,
                "beats": [],
                "downbeats": [],
                "candidates": [],
                "hop": 0.1,
                "energy": [0.5] * int(SECONDS * 10),
                "warnings": [],
            }
        )
    )
    sections: dict = {"sections": MV_SECTIONS}
    if range_ is not None:
        sections["range"] = {"start": range_[0], "end": range_[1]}
    (workdir / "music" / "sections.json").write_text(json.dumps(sections))
    (workdir / "beatsheet" / "beatsheet.json").write_text(
        json.dumps(
            {
                "sections": [
                    {"ref": s["id"], "intent": "x", "energy": "low", "moments": []}
                    for s in MV_SECTIONS
                    if refs is None or s["id"] in refs
                ]
            }
        )
    )
    fx.write_project(workdir, scenes={s["id"]: fx.PURE_SCENE_PLAIN for s in MV_SECTIONS})
    return digest
