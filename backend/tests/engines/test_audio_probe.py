"""`engines.audio.probe`: ffprobe-based validation of an uploaded file."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from engines.audio_fixtures import SAMPLE_RATE
from fixtures.audio_engine import write_wav
from studio.engines.audio.probe import AudioProbe, AudioProbeError, probe_audio


async def test_probe_reads_duration_and_codec(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "a.wav", np.zeros(SAMPLE_RATE * 3), SAMPLE_RATE)
    probe = await probe_audio(path)
    assert isinstance(probe, AudioProbe)
    assert probe.duration == pytest.approx(3.0, abs=0.05)
    assert probe.codec.startswith("pcm")


async def test_probe_rejects_text_posing_as_audio(tmp_path: Path) -> None:
    path = tmp_path / "fake.mp3"
    path.write_text("not audio at all", encoding="utf-8")
    with pytest.raises(AudioProbeError, match="音频"):
        await probe_audio(path)


async def test_probe_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.wav"
    path.write_bytes(b"")
    with pytest.raises(AudioProbeError):
        await probe_audio(path)


async def test_probe_reports_missing_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_wav(tmp_path / "a.wav", np.zeros(SAMPLE_RATE), SAMPLE_RATE)
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    with pytest.raises(AudioProbeError, match="ffprobe"):
        await probe_audio(path)


async def test_probe_times_out(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "a.wav", np.zeros(SAMPLE_RATE), SAMPLE_RATE)
    with pytest.raises(AudioProbeError, match="超时"):
        await probe_audio(path, timeout=0.0001)
