"""Real `music/` products for a project workspace, made by the reference synthesis script.

Used by the worker and api tests that need a rendered score on disk (3B). No sandbox: the script
is the trusted reference fixture; the sandboxed run is covered by the slow tests of 3A.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from studio.stages.music.render import RenderOutcome, render_music_core
from studio.stages.music.sources import infer_sources
from studio.timeline.load import load_timeline

REF = Path(__file__).with_name("compose_ref.py")


def _identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


async def render_products(workdir: Path, *, script: Path = REF) -> RenderOutcome:
    """Write `music/compose.py` and render it against the workspace's current timeline."""
    (workdir / "music").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(script, workdir / "music" / "compose.py")
    loaded = load_timeline(infer_sources(workdir, "", with_music=False))
    energy = {s["id"]: s["energy"] for s in (loaded.beatsheet or {}).get("sections", [])}
    outcome = await render_music_core(
        workdir,
        timeline=loaded.timeline.model_dump(mode="json"),
        base_hash=loaded.base_hash,
        section_energy=energy,
        wrap_command=_identity,
    )
    assert outcome.ok, outcome.errors
    return outcome
