"""Real `music/` products for a project workspace, made by the reference synthesis script.

Used by the worker and api tests that need a rendered score on disk (3B). No sandbox: the script
is the trusted reference fixture; the sandboxed run is covered by the slow tests of 3A.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from studio.stages.common.score.render import RenderOutcome, render_music_core
from studio.stages.common.score.sources import infer_sources
from studio.timeline.load import load_timeline

REF = Path(__file__).with_name("compose_ref.py")
FREE = Path(__file__).with_name("compose_free.py")


def _identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


async def render_products(workdir: Path, *, script: Path = REF) -> RenderOutcome:
    """Explainer bed: write `music/compose.py` and render it against the workspace's timeline."""
    (workdir / "music").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(script, workdir / "music" / "compose.py")
    loaded = load_timeline(infer_sources(workdir, "", with_music=False))
    outcome = await render_music_core(
        workdir,
        timeline=loaded.timeline.model_dump(mode="json"),
        base_hash=loaded.base_hash,
        wrap_command=_identity,
    )
    assert outcome.ok, outcome.errors
    return outcome


async def render_free_products(workdir: Path) -> RenderOutcome:
    """The `produce` form: the free-form script renders with no timeline (16 s, 120 BPM)."""
    (workdir / "music").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FREE, workdir / "music" / "compose.py")
    outcome = await render_music_core(workdir, wrap_command=_identity)
    assert outcome.ok, outcome.errors
    return outcome
