"""`render_music_core` without a timeline (produce-stage 设计 §5.3、§6, plan T3).

The script decides tempo, length and structure itself: no `STUDIO_TIMELINE`, no retime check,
`render.json` without `base_hash`, `bpm` optional.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from studio.engines.audio.runner import WrapCommand
from studio.stages.common.score.render import RenderOutcome, render_music_core

FREE = Path(__file__).resolve().parents[1] / "fixtures" / "synth_music" / "compose_free.py"
PRODUCTS = ("music.wav", "events.json", "analysis.json", "analysis.png", "render.json")


def identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "music").mkdir()
    shutil.copyfile(FREE, tmp_path / "music" / "compose.py")
    return tmp_path


async def _render(workdir: Path, wrap: WrapCommand = identity) -> RenderOutcome:
    return await render_music_core(workdir, wrap_command=wrap)


async def test_renders_without_a_timeline(workdir: Path) -> None:
    outcome = await _render(workdir)
    assert outcome.ok, outcome.errors
    assert all((workdir / "music" / name).is_file() for name in PRODUCTS)
    assert outcome.written == [f"music/{name}" for name in PRODUCTS]
    assert outcome.declared_bpm == 120.0 and outcome.event_count > 20


async def test_render_json_has_no_base_hash(workdir: Path) -> None:
    await _render(workdir)
    record = json.loads((workdir / "music" / "render.json").read_text(encoding="utf-8"))
    assert set(record) == {"script_hash", "wav_hash", "bpm", "duration", "rendered_at"}
    assert abs(record["duration"] - 16.0) < 0.01 and record["bpm"] == 120.0


async def test_there_is_no_retime_check_for_a_script_that_picks_its_own_length(
    workdir: Path,
) -> None:
    outcome = await _render(workdir)
    assert outcome.ok and "重定时" not in outcome.retime_note


async def test_bpm_is_optional(workdir: Path) -> None:
    script = workdir / "music" / "compose.py"
    script.write_text(
        script.read_text(encoding="utf-8").replace('document["bpm"] = BPM', "pass"),
        encoding="utf-8",
    )
    outcome = await _render(workdir)
    assert outcome.ok, outcome.errors
    assert outcome.declared_bpm is None
    assert outcome.report is not None and outcome.report.grid_alignment is None
    record = json.loads((workdir / "music" / "render.json").read_text(encoding="utf-8"))
    assert record["bpm"] is None


async def test_declared_bpm_gives_a_grid_alignment_figure(workdir: Path) -> None:
    outcome = await _render(workdir)
    assert outcome.report is not None and outcome.report.grid_alignment is not None
    assert outcome.report.grid_alignment > 0.8


def _patch_events(workdir: Path, **changes: object) -> None:
    script = workdir / "music" / "compose.py"
    source = script.read_text(encoding="utf-8")
    marker = "    json.dump(document, handle)"
    patch = "".join(f"    document[{k!r}] = {v!r}\n" for k, v in changes.items())
    script.write_text(source.replace(marker, patch + marker), encoding="utf-8")


async def test_declared_duration_must_match_the_audio(workdir: Path) -> None:
    _patch_events(workdir, duration=10.0)
    outcome = await _render(workdir)
    assert not outcome.ok
    assert any("duration" in e and "10" in e and "16" in e for e in outcome.errors), outcome.errors
    assert not (workdir / "music" / "music.wav").exists()


async def test_declared_bpm_must_be_in_range(workdir: Path) -> None:
    _patch_events(workdir, bpm=999)
    outcome = await _render(workdir)
    assert not outcome.ok and any("bpm" in e for e in outcome.errors)


async def test_events_must_stay_inside_the_audio(workdir: Path) -> None:
    _patch_events(workdir, events=[{"name": "late", "kind": "onset", "start": 20.0, "end": 20.1}])
    outcome = await _render(workdir)
    assert not outcome.ok and any("late" in e for e in outcome.errors)


async def test_a_failing_run_leaves_the_old_products_alone(workdir: Path) -> None:
    await _render(workdir)
    before = (workdir / "music" / "music.wav").read_bytes()
    (workdir / "music" / "compose.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    outcome = await _render(workdir)
    assert not outcome.ok
    assert (workdir / "music" / "music.wav").read_bytes() == before


async def test_missing_script_is_reported(tmp_path: Path) -> None:
    outcome = await _render(tmp_path)
    assert not outcome.ok and "compose.py" in outcome.errors[0]


async def test_very_many_events_are_reported_without_flooding(workdir: Path) -> None:
    flood = [{"name": "x", "kind": "onset", "start": 99.0 + i, "end": 99.5 + i} for i in range(900)]
    _patch_events(workdir, events=flood)
    outcome = await _render(workdir)
    assert not outcome.ok
    assert len("\n".join(outcome.errors)) < 8_000
