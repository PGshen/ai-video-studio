"""`engines.audio.song_job`: isolated song analysis in a subprocess (4A T3)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from engines.audio_fixtures import SAMPLE_RATE, click_track
from fixtures.audio_engine import write_wav
from studio.engines.audio import song_job
from studio.engines.audio.runner import limited_argv
from studio.engines.audio.song_job import SongJobError, run_song_analysis


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("job")
    return write_wav(directory / "song.wav", click_track(120.0, 0.5, 12.0), SAMPLE_RATE)


async def test_job_writes_analysis_and_picture(source: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = await run_song_analysis(source, out_dir)
    assert result.analysis_path == out_dir / "analysis.json"
    assert result.picture_path == out_dir / "analysis.png"
    document = json.loads(result.analysis_path.read_text())
    assert document["bpm"] == pytest.approx(120.0, rel=0.01)
    assert len(document["source_hash"]) == 64
    assert Image.open(result.picture_path).size == (1800, 1000)
    assert result.elapsed > 0


async def test_job_reports_silence_and_leaves_no_artifacts(tmp_path: Path) -> None:
    silent = write_wav(tmp_path / "silent.wav", np.zeros(SAMPLE_RATE * 10), SAMPLE_RATE)
    out_dir = tmp_path / "out"
    with pytest.raises(SongJobError, match="静音"):
        await run_song_analysis(silent, out_dir)
    assert not any(out_dir.iterdir())


async def test_job_reports_a_missing_source(tmp_path: Path) -> None:
    with pytest.raises(SongJobError, match="不存在"):
        await run_song_analysis(tmp_path / "nope.wav", tmp_path / "out")


async def test_timeout_kills_the_whole_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time;"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        f"open({str(pid_file)!r}, 'w').write(str(p.pid));"
        "time.sleep(60)"
    )
    monkeypatch.setattr(
        song_job,
        "_command",
        lambda source, out_dir, timeout: limited_argv([sys.executable, "-c", code], 30),
    )
    with pytest.raises(SongJobError, match="超时"):
        await run_song_analysis(tmp_path / "x.wav", tmp_path / "out", timeout=1.5)
    grandchild = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("grandchild process survived the timeout")


async def test_missing_artifact_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        song_job, "_command", lambda source, out_dir, timeout: [sys.executable, "-c", "pass"]
    )
    with pytest.raises(SongJobError, match="analysis.json"):
        await run_song_analysis(tmp_path / "x.wav", tmp_path / "out")
