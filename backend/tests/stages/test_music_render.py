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
from studio.stages.music.render import RenderOutcome, render_music_core
from studio.stages.music.sources import infer_sources
from studio.timeline.load import load_timeline

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REF = FIXTURES / "synth_music" / "compose_ref.py"
HARDCODED = FIXTURES / "synth_music" / "compose_hardcoded.py"
ANIMATION = FIXTURES / "animation"
BPM = 128.0
PRODUCTS = ("music.wav", "events.json", "analysis.json", "analysis.png", "render.json")


def identity(argv: list[str], env: dict[str, str]) -> list[str]:
    return argv


def _beatsheet(bars: tuple[int, ...] = (3, 3)) -> dict[str, Any]:
    energies = ["low", "peak", "mid", "high"]
    return {
        "bpm": BPM,
        "sections": [
            {
                "id": f"s{i + 1}",
                "label": f"S{i + 1}",
                "bars": b,
                "intent": "x",
                "energy": energies[i],
                "moments": [{"at": "1.1", "visual_action": "a"}],
            }
            for i, b in enumerate(bars)
        ],
    }


@pytest.fixture
def reel(tmp_path: Path) -> Path:
    path = tmp_path / "upstream" / "beatsheet"
    path.mkdir(parents=True)
    (path / "beatsheet.json").write_text(json.dumps(_beatsheet()), encoding="utf-8")
    (tmp_path / "music").mkdir()
    shutil.copyfile(REF, tmp_path / "music" / "compose.py")
    return tmp_path


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
    energy = {s["id"]: s["energy"] for s in (loaded.beatsheet or {}).get("sections", [])}
    return await render_music_core(
        workdir,
        timeline=loaded.timeline.model_dump(mode="json"),
        base_hash=loaded.base_hash,
        section_energy=energy,
        wrap_command=wrap,
        **kw,
    )


def _leftovers(workdir: Path) -> list[Path]:
    return (
        list((workdir / ".cache" / "tmp").glob("music-run-*"))
        if (workdir / ".cache").exists()
        else []
    )


async def test_reel_success_writes_the_five_products_with_consistent_hashes(reel: Path) -> None:
    outcome = await _render(reel)
    assert outcome.ok, outcome.errors
    for name in PRODUCTS:
        assert (reel / "music" / name).is_file(), name
    assert outcome.png is not None and outcome.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert outcome.report is not None and outcome.report.duration == pytest.approx(11.25, abs=0.02)

    render = json.loads((reel / "music" / "render.json").read_text())
    loaded = load_timeline(infer_sources(reel, "upstream/", with_music=False))
    assert (
        render["script_hash"]
        == hashlib.sha256((reel / "music" / "compose.py").read_bytes()).hexdigest()
    )
    assert (
        render["wav_hash"]
        == hashlib.sha256((reel / "music" / "music.wav").read_bytes()).hexdigest()
    )
    assert render["base_hash"] == loaded.base_hash
    assert render["bpm"] == BPM and render["duration"] == pytest.approx(11.25)

    analysis = json.loads((reel / "music" / "analysis.json").read_text())
    assert analysis["hop"] == 0.1 and len(analysis["energy"]) == int(11.25 / 0.1) + 1
    assert len(analysis["waveform"]) == 1000 and analysis["wav_hash"] == render["wav_hash"]
    assert "rms_dbfs" in analysis["metrics"]
    assert _leftovers(reel) == []


async def test_the_script_runs_twice_the_second_time_on_a_retimed_timeline(reel: Path) -> None:
    seen: list[dict[str, Any]] = []

    def spy(argv: list[str], env: dict[str, str]) -> list[str]:
        timeline = json.loads(Path(env["STUDIO_TIMELINE"]).read_text())
        seen.append({"duration": timeline["duration"], "bpm": timeline["grid"]["bpm"]})
        return argv

    outcome = await _render(reel, spy)
    assert outcome.ok, outcome.errors
    assert len(seen) == 2
    assert seen[1]["bpm"] == pytest.approx(BPM * 0.8)
    assert seen[1]["duration"] == pytest.approx(seen[0]["duration"] * 1.25)
    assert "重定时" in outcome.retime_note


async def test_a_script_with_hard_coded_time_is_rejected_and_old_products_stay(reel: Path) -> None:
    shutil.copyfile(HARDCODED, reel / "music" / "compose.py")
    for name in PRODUCTS:
        (reel / "music" / name).write_bytes(b"old " + name.encode())
    outcome = await _render(reel)
    assert not outcome.ok
    assert any("写死" in e for e in outcome.errors)
    for name in PRODUCTS:
        assert (reel / "music" / name).read_bytes() == b"old " + name.encode()
    assert _leftovers(reel) == []


@pytest.mark.parametrize(
    ("script", "needle"),
    [
        ("raise RuntimeError('boom in script')\n", "boom in script"),
        ("print('does nothing')\n", "STUDIO_OUT_WAV"),
    ],
)
async def test_script_failures_are_reported_and_old_products_stay(
    reel: Path, script: str, needle: str
) -> None:
    (reel / "music" / "compose.py").write_text(script)
    (reel / "music" / "music.wav").write_bytes(b"old")
    outcome = await _render(reel)
    assert not outcome.ok and any(needle in e for e in outcome.errors)
    assert (reel / "music" / "music.wav").read_bytes() == b"old"
    assert not (reel / "music" / "render.json").exists()
    assert _leftovers(reel) == []


async def test_timeout_is_reported(reel: Path) -> None:
    (reel / "music" / "compose.py").write_text("import time\ntime.sleep(30)\n")
    outcome = await _render(reel, timeout=1.0)
    assert not outcome.ok and any("超时" in e for e in outcome.errors)


async def test_missing_script_is_reported(reel: Path) -> None:
    (reel / "music" / "compose.py").unlink()
    outcome = await _render(reel)
    assert not outcome.ok and any("compose.py" in e for e in outcome.errors)


@pytest.mark.parametrize(
    ("patch", "needle"),
    [
        ('doc["bpm"] = 100.0', "bpm"),
        ('doc["duration"] = 99.0', "duration"),
        ('doc["events"] = "x"', "events"),
    ],
)
async def test_invalid_events_documents_fail_before_anything_is_written(
    reel: Path, patch: str, needle: str
) -> None:
    script = REF.read_text().replace("json.dump(doc, open(", f"{patch}\njson.dump(doc, open(", 1)
    (reel / "music" / "compose.py").write_text(script)
    outcome = await _render(reel)
    assert not outcome.ok and any(needle in e for e in outcome.errors), outcome.errors
    assert not (reel / "music" / "music.wav").exists()


async def test_wrong_audio_length_and_unreadable_wav_fail(reel: Path) -> None:
    short = REF.read_text().replace(
        "n = int(round(duration * SR))", "n = int(round(duration * SR / 2))"
    )
    (reel / "music" / "compose.py").write_text(short)
    outcome = await _render(reel)
    assert not outcome.ok and any("时长" in e for e in outcome.errors)
    garbage = REF.read_text().replace(
        "wav.close()", "wav.close()\nopen(os.environ['STUDIO_OUT_WAV'], 'wb').write(b'junk')", 1
    )
    (reel / "music" / "compose.py").write_text(garbage)
    assert not (await _render(reel)).ok


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


async def test_energy_trend_warning_uses_the_beatsheet_labels(reel: Path) -> None:
    outcome = await _render(reel)
    assert outcome.ok and outcome.report is not None
    # s1 low -> s2 peak: the reference script gets louder, so no trend warning
    assert not any("要求能量上升" in w for w in outcome.report.warnings)
    flat = REF.read_text().replace(
        "return 0.35 + 0.65 * index / max(1, len(sections) - 1)", "return 0.5"
    )
    (reel / "music" / "compose.py").write_text(flat)
    flat_outcome = await _render(reel)
    assert flat_outcome.report is not None
    assert any("要求能量上升" in w for w in flat_outcome.report.warnings)
