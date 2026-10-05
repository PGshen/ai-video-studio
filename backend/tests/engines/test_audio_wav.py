"""`engines.audio.wav.read_wav`：各种 WAV 格式的读取与超限、损坏的拒绝（子项目 3 设计 §7.3）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fixtures.audio_engine import SR, write_wav
from studio.engines.audio.wav import AudioError, read_wav


def _tone(seconds: float = 0.5, sr: int = SR) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return 0.5 * np.sin(2 * np.pi * 440 * t)


@pytest.mark.parametrize("kind", ["pcm16", "pcm24", "pcm32", "float32"])
def test_formats_round_trip_to_float_samples(tmp_path: Path, kind: str) -> None:
    tone = _tone()
    samples = read_wav(write_wav(tmp_path / "a.wav", tone, kind=kind))
    assert samples.sample_rate == SR
    assert samples.data.shape == tone.shape
    assert np.max(np.abs(samples.data - tone)) < (1e-3 if kind == "pcm16" else 1e-5)


def test_stereo_keeps_two_channels(tmp_path: Path) -> None:
    tone = _tone()
    stereo = np.stack([tone, tone * 0.5], axis=1)
    samples = read_wav(write_wav(tmp_path / "s.wav", stereo, kind="pcm16"))
    assert samples.data.shape == (len(tone), 2)
    assert samples.channels == 2
    assert samples.mono().shape == (len(tone),)
    assert samples.duration == pytest.approx(0.5, abs=1e-3)


def test_sample_rate_outside_the_supported_range_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AudioError, match="采样率"):
        read_wav(write_wav(tmp_path / "low.wav", _tone(sr=8000), sr=8000))
    with pytest.raises(AudioError, match="采样率"):
        read_wav(write_wav(tmp_path / "high.wav", _tone(0.1, sr=192000), sr=192000))


def test_missing_file_garbage_and_truncated_data_are_refused(tmp_path: Path) -> None:
    with pytest.raises(AudioError, match="不存在"):
        read_wav(tmp_path / "none.wav")
    (tmp_path / "junk.wav").write_bytes(b"not a wav file at all")
    with pytest.raises(AudioError, match="WAV"):
        read_wav(tmp_path / "junk.wav")
    good = write_wav(tmp_path / "ok.wav", _tone(), kind="pcm16").read_bytes()
    (tmp_path / "cut.wav").write_bytes(good[:20])
    with pytest.raises(AudioError):
        read_wav(tmp_path / "cut.wav")


def test_unsupported_encoding_is_refused(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "a.wav", _tone(), kind="pcm16")
    raw = bytearray(path.read_bytes())
    raw[20:22] = (7).to_bytes(2, "little")  # mu-law
    path.write_bytes(bytes(raw))
    with pytest.raises(AudioError, match="编码"):
        read_wav(path)


def test_size_and_duration_limits(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "a.wav", _tone(1.0), kind="pcm16")
    with pytest.raises(AudioError, match="大小"):
        read_wav(path, max_bytes=100)
    with pytest.raises(AudioError, match="时长"):
        read_wav(path, max_seconds=0.5)


def test_empty_audio_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AudioError, match="没有"):
        read_wav(write_wav(tmp_path / "e.wav", np.zeros(0)))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_samples_are_refused(tmp_path: Path, bad: float) -> None:
    data = 0.3 * np.sin(np.arange(SR) * 0.05)
    path = write_wav(tmp_path / "bad.wav", data, kind="float32")
    raw = bytearray(path.read_bytes())  # `write_wav` clips, so patch the bad sample in by hand
    raw[44 + 1000 * 4 : 44 + 1001 * 4] = np.float32(bad).tobytes()
    path.write_bytes(bytes(raw))
    with pytest.raises(AudioError, match="NaN|无穷"):
        read_wav(path)
