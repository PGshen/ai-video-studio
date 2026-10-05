"""`engines.audio.song`: decoding via ffmpeg and constant-grid fitting (4A T1)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from engines.audio_fixtures import SAMPLE_RATE, click_track
from fixtures.audio_engine import write_wav
from studio.engines.audio import song
from studio.engines.audio.song import MAX_SONG_SECONDS, decode_song, fit_grid
from studio.engines.audio.wav import AudioError
from studio.timeline import build


def _beats(bpm: float, offset: float, count: int, noise: float = 0.0) -> list[float]:
    rng = np.random.default_rng(1)
    return [offset + i * 60.0 / bpm + float(rng.normal(0, noise)) for i in range(count)]


def _offset_error(fit_offset: float, offset: float, bpm: float) -> float:
    """Offset difference modulo one beat: the fit may name any beat as beat 0."""
    period = 60.0 / bpm
    delta = (fit_offset - offset) % period
    return min(delta, period - delta)


def test_bpm_range_matches_timeline() -> None:
    assert (song.BPM_MIN, song.BPM_MAX) == build.BPM_RANGE


def test_fit_grid_recovers_noisy_beats() -> None:
    fit = fit_grid(_beats(120.0, 0.08, 200, noise=0.008))
    assert fit.bpm == pytest.approx(120.0, rel=0.005)
    assert fit.offset == pytest.approx(0.08, abs=0.03)
    assert 0 < fit.residual_ms < 20


def test_fit_grid_rejects_outlier_beats() -> None:
    beats = _beats(100.0, 0.5, 120)
    beats[10] += 0.2
    beats[50] -= 0.15
    del beats[70]  # a missed beat must not shift later indices
    fit = fit_grid(beats)
    assert fit.bpm == pytest.approx(100.0, rel=0.002)
    assert fit.residual_ms < 1.0


def test_fit_grid_folds_double_and_half_tempo() -> None:
    assert fit_grid(_beats(280.0, 0.1, 100)).bpm == pytest.approx(140.0, rel=0.002)
    assert fit_grid(_beats(40.0, 0.1, 30)).bpm == pytest.approx(80.0, rel=0.002)


def test_fit_grid_rejects_unusable_input() -> None:
    with pytest.raises(AudioError, match="拍点"):
        fit_grid([1.0])
    with pytest.raises(AudioError, match="拍点"):
        fit_grid([])
    with pytest.raises(AudioError, match="递增"):
        fit_grid([2.0, 2.0, 2.0, 2.0, 2.0])


@pytest.mark.parametrize("bpm", [120.0, 96.0, 140.0])
def test_decoded_click_track_beats_fit_the_grid(tmp_path: Path, bpm: float) -> None:
    import librosa

    wav = write_wav(tmp_path / "c.wav", click_track(bpm, 0.08, 30.0), SAMPLE_RATE)
    samples = decode_song(wav)
    assert samples.sample_rate == song.ANALYSIS_SAMPLE_RATE
    assert samples.channels == 1
    assert samples.duration == pytest.approx(30.0, abs=0.05)
    _, beat_times = librosa.beat.beat_track(y=samples.data, sr=samples.sample_rate, units="time")
    fit = fit_grid([float(t) for t in beat_times])
    assert fit.bpm == pytest.approx(bpm, rel=0.005)
    assert _offset_error(fit.offset, 0.08, bpm) < 0.03


def test_decode_resamples_and_downmixes(tmp_path: Path) -> None:
    mono = click_track(120.0, 0.0, 6.0, 44100)
    stereo = np.stack([mono, mono * 0.5], axis=1)
    samples = decode_song(write_wav(tmp_path / "s.wav", stereo, 44100))
    assert samples.sample_rate == 22050
    assert samples.channels == 1
    assert samples.duration == pytest.approx(6.0, abs=0.05)


def test_decode_errors_are_chinese(tmp_path: Path) -> None:
    with pytest.raises(AudioError, match="不存在"):
        decode_song(tmp_path / "missing.wav")
    silent = write_wav(tmp_path / "silent.wav", np.zeros(SAMPLE_RATE * 10), SAMPLE_RATE)
    with pytest.raises(AudioError, match="静音"):
        decode_song(silent)
    short = write_wav(tmp_path / "short.wav", click_track(120.0, 0.0, 3.0), SAMPLE_RATE)
    with pytest.raises(AudioError, match="过短|太短"):
        decode_song(short)
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"this is not audio" * 100)
    with pytest.raises(AudioError, match="解码"):
        decode_song(broken)
    with pytest.raises(AudioError, match="ffmpeg"):
        decode_song(short, ffmpeg="definitely-not-ffmpeg")


def test_max_song_seconds_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert MAX_SONG_SECONDS == 600
    monkeypatch.setattr(song, "MAX_SONG_SECONDS", 8.0)
    ok = write_wav(tmp_path / "ok.wav", click_track(120.0, 0.0, 7.5), SAMPLE_RATE)
    assert decode_song(ok).duration == pytest.approx(7.5, abs=0.05)
    long = write_wav(tmp_path / "long.wav", click_track(120.0, 0.0, 8.6), SAMPLE_RATE)
    with pytest.raises(AudioError, match="过长|超过"):
        decode_song(long)
