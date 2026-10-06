"""`render_music_core`：运行脚本、校验、重定时、写回产物（子项目 3 设计 §7.4）。

用恒等的 `wrap_command`（不依赖沙箱）和参考合成脚本；
真实 Seatbelt 见 `test_music_tool.py` 的 slow 用例。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from studio.engines.audio.runner import WrapCommand
from studio.stages.common.score.render import RenderOutcome, render_music_core
from studio.stages.common.score.sources import infer_sources
from studio.timeline.load import load_timeline

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REF = FIXTURES / "synth_music" / "compose_ref.py"
ANIMATION = FIXTURES / "animation"
PRODUCTS = ("music.wav", "events.json", "analysis.json", "analysis.png", "render.json")


def identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


@pytest.fixture
def explainer(tmp_path: Path) -> Path:
    target = tmp_path / "upstream" / "narrative"
    target.mkdir(parents=True)
    for name in ("narrative.json", "timing.json"):
        shutil.copyfile(ANIMATION / name, target / name)
    (tmp_path / "music").mkdir()
    shutil.copyfile(REF, tmp_path / "music" / "compose.py")
    return tmp_path


async def _render(workdir: Path, wrap: WrapCommand = identity, **kw: Any) -> RenderOutcome:
    loaded = load_timeline(infer_sources(workdir, "upstream/", with_music=False))
    return await render_music_core(
        workdir,
        timeline=loaded.timeline.model_dump(mode="json"),
        base_hash=loaded.base_hash,
        wrap_command=wrap,
        **kw,
    )


def _leftovers(workdir: Path) -> list[Path]:
    return (
        list((workdir / ".cache" / "tmp").glob("music-run-*"))
        if (workdir / ".cache").exists()
        else []
    )


async def test_success_writes_the_five_products_with_consistent_hashes(explainer: Path) -> None:
    outcome = await _render(explainer)
    assert outcome.ok, outcome.errors
    for name in PRODUCTS:
        assert (explainer / "music" / name).is_file(), name
    assert outcome.png is not None and outcome.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert outcome.report is not None and outcome.report.duration == pytest.approx(3.0, abs=0.02)

    render = json.loads((explainer / "music" / "render.json").read_text())
    loaded = load_timeline(infer_sources(explainer, "upstream/", with_music=False))
    assert (
        render["script_hash"]
        == hashlib.sha256((explainer / "music" / "compose.py").read_bytes()).hexdigest()
    )
    assert (
        render["wav_hash"]
        == hashlib.sha256((explainer / "music" / "music.wav").read_bytes()).hexdigest()
    )
    assert render["base_hash"] == loaded.base_hash
    assert render["bpm"] == 100.0 and render["duration"] == pytest.approx(3.0)

    analysis = json.loads((explainer / "music" / "analysis.json").read_text())
    assert analysis["hop"] == 0.1 and len(analysis["energy"]) == int(3.0 / 0.1) + 1
    assert len(analysis["waveform"]) == 1000 and analysis["wav_hash"] == render["wav_hash"]
    assert "rms_dbfs" in analysis["metrics"]
    assert _leftovers(explainer) == []


async def test_a_script_with_hard_coded_time_is_rejected_and_old_products_stay(
    explainer: Path,
) -> None:
    loaded = load_timeline(infer_sources(explainer, "upstream/", with_music=False))
    hard = REF.read_text().replace(
        'duration = timeline["duration"]', f"duration = {loaded.timeline.duration!r}"
    )
    assert hard != REF.read_text()
    (explainer / "music" / "compose.py").write_text(hard)
    for name in PRODUCTS:
        (explainer / "music" / name).write_bytes(b"old " + name.encode())
    outcome = await _render(explainer)
    assert not outcome.ok
    assert any("写死" in e for e in outcome.errors)
    for name in PRODUCTS:
        assert (explainer / "music" / name).read_bytes() == b"old " + name.encode()
    assert _leftovers(explainer) == []


@pytest.mark.parametrize(
    ("script", "needle"),
    [
        ("raise RuntimeError('boom in script')\n", "boom in script"),
        ("print('does nothing')\n", "STUDIO_OUT_WAV"),
    ],
)
async def test_script_failures_are_reported_and_old_products_stay(
    explainer: Path, script: str, needle: str
) -> None:
    (explainer / "music" / "compose.py").write_text(script)
    (explainer / "music" / "music.wav").write_bytes(b"old")
    outcome = await _render(explainer)
    assert not outcome.ok and any(needle in e for e in outcome.errors)
    assert (explainer / "music" / "music.wav").read_bytes() == b"old"
    assert not (explainer / "music" / "render.json").exists()
    assert _leftovers(explainer) == []


async def test_timeout_is_reported(explainer: Path) -> None:
    (explainer / "music" / "compose.py").write_text("import time\ntime.sleep(30)\n")
    outcome = await _render(explainer, timeout=1.0)
    assert not outcome.ok and any("超时" in e for e in outcome.errors)


async def test_missing_script_is_reported(explainer: Path) -> None:
    (explainer / "music" / "compose.py").unlink()
    outcome = await _render(explainer)
    assert not outcome.ok and any("compose.py" in e for e in outcome.errors)


@pytest.mark.parametrize(
    ("patch", "needle"),
    [
        ('doc["bpm"] = 999.0', "bpm"),
        ('doc["duration"] = 99.0', "duration"),
        ('doc["events"] = "x"', "events"),
    ],
)
async def test_invalid_events_documents_fail_before_anything_is_written(
    explainer: Path, patch: str, needle: str
) -> None:
    script = REF.read_text().replace("json.dump(doc, open(", f"{patch}\njson.dump(doc, open(", 1)
    (explainer / "music" / "compose.py").write_text(script)
    outcome = await _render(explainer)
    assert not outcome.ok and any(needle in e for e in outcome.errors), outcome.errors
    assert not (explainer / "music" / "music.wav").exists()


async def test_wrong_audio_length_and_unreadable_wav_fail(explainer: Path) -> None:
    short = REF.read_text().replace(
        "n = int(round(duration * SR))", "n = int(round(duration * SR / 2))"
    )
    (explainer / "music" / "compose.py").write_text(short)
    outcome = await _render(explainer)
    assert not outcome.ok and any("时长" in e for e in outcome.errors)
    garbage = REF.read_text().replace(
        "wav.close()", "wav.close()\nopen(os.environ['STUDIO_OUT_WAV'], 'wb').write(b'junk')", 1
    )
    (explainer / "music" / "compose.py").write_text(garbage)
    assert not (await _render(explainer)).ok


async def test_explainer_bed_declares_its_own_grid_and_is_retimed_by_duration(
    explainer: Path,
) -> None:
    seen: list[float] = []

    def spy(argv: list[str], env: dict[str, str]) -> list[str]:
        seen.append(json.loads(Path(env["STUDIO_TIMELINE"]).read_text())["duration"])
        return argv

    outcome = await _render(explainer, spy)
    assert outcome.ok, outcome.errors
    assert len(seen) == 2 and seen[1] == pytest.approx(seen[0] * 1.25)
    render = json.loads((explainer / "music" / "render.json").read_text())
    assert render["bpm"] == 100.0
    events = json.loads((explainer / "music" / "events.json").read_text())
    assert events["offset"] == 0.1


async def test_the_run_uses_a_snapshot_of_the_script_taken_when_it_started(explainer: Path) -> None:
    """A script edited while a render is running (the agent, or the 3B api) must not leave the
    hash describing one program and the audio coming from another."""
    original = explainer / "music" / "compose.py"
    source = original.read_text()
    original.write_text(
        f"import pathlib\npathlib.Path({str(original)!r}).write_text('raise SystemExit(9)')\n"
        + source
    )
    started = original.read_bytes()
    outcome = await _render(explainer)
    assert outcome.ok, outcome.errors
    render = json.loads((explainer / "music" / "render.json").read_text())
    assert render["script_hash"] == hashlib.sha256(started).hexdigest()


async def test_analysis_does_not_block_the_event_loop(
    explainer: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import time

    from studio.stages.common.score import render as render_module

    real = render_module.analyze

    def slow(*args: Any, **kwargs: Any) -> Any:
        time.sleep(0.4)
        return real(*args, **kwargs)

    monkeypatch.setattr(render_module, "analyze", slow)
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        outcome = await _render(explainer)
    finally:
        task.cancel()
    assert outcome.ok, outcome.errors
    assert ticks > 40  # two analyses of 0.4 s each ran off the loop
