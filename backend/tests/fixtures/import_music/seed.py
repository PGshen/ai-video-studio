"""A music-video project (imported song): `concept → produce`."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

from fixtures.synth_music.seed import _create
from studio.workspace import BlobStore

MV_PIPELINE = ["concept", "produce"]


def seed_mv_project(engine: Engine, blobs: BlobStore, *, data_dir: Path) -> str:
    settings = {
        "video_kind": "music_video",
        "engine": "html",
        "narration": False,
        "music_source": "import",
        "pipeline": MV_PIPELINE,
    }
    return _create(engine, blobs, data_dir, settings, MV_PIPELINE)[0]
