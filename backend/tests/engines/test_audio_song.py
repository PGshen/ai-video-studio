"""`engines.audio.song`: decoding via ffmpeg and constant-grid fitting (4A T1)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from engines.audio_fixtures import SAMPLE_RATE, click_times, click_track
from fixtures.audio_engine import write_wav
from studio.engines.audio import song
from studio.engines.audio.song import (
    MAX_SONG_SECONDS,
    analyze_song,
    decode_song,
    fit_grid,
)
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


def test_fit_grid_survives_a_dropped_first_beat_and_a_spurious_one() -> None:
    dropped = _beats(100.0, 0.5, 120)[1:]  # beat_track often misses the very first beat
    fit = fit_grid(dropped)
    assert fit.bpm == pytest.approx(100.0, rel=0.002)
    assert _offset_error(fit.offset, 0.5, 100.0) < 0.002
    spurious = [0.5 - 0.17, *_beats(100.0, 0.5, 120)]  # an extra beat before the first one
    fit = fit_grid(spurious)
    assert fit.bpm == pytest.approx(100.0, rel=0.002)
    assert fit.residual_ms < 1.0
    assert fit.beats_used == 120


def test_fit_grid_ignores_a_half_period_extra_beat() -> None:
    beats = _beats(100.0, 0.5, 120)
    beats.insert(30, beats[29] + 0.3)  # exactly half a period after beat 29
    fit = fit_grid(beats)
    assert fit.bpm == pytest.approx(100.0, rel=0.002)
    assert fit.residual_ms < 1.0
    assert fit.beats_used == 120


def test_fit_grid_folds_double_and_half_tempo() -> None:
    assert fit_grid(_beats(280.0, 0.1, 100)).bpm == pytest.approx(140.0, rel=0.002)
    assert fit_grid(_beats(40.0, 0.1, 30)).bpm == pytest.approx(80.0, rel=0.002)


def _confidence(fit: song.GridFit, duration: float) -> float:
    period = 60.0 / fit.bpm
    fitness = max(
        0.0, 1.0 - fit.residual_ms / (song.CONFIDENCE_RESIDUAL_FRACTION * period * 1000.0)
    )
    return fitness * song._coverage(fit, duration)


def test_coverage_of_slow_regular_beats_is_not_halved_by_folding() -> None:
    duration = 120.0
    fit = fit_grid(_beats(50.0, 0.1, 100))  # period 1.2 s, folded to 100 BPM
    assert fit.bpm == pytest.approx(100.0, rel=0.002)
    assert fit.raw_period == pytest.approx(1.2, rel=0.002)
    assert song._coverage(fit, duration) == pytest.approx(1.0, abs=0.02)
    assert _confidence(fit, duration) >= song.CONFIDENCE_WARN


def test_coverage_of_regular_120_bpm_beats_is_full() -> None:
    fit = fit_grid(_beats(120.0, 0.08, 200))
    assert fit.raw_period == pytest.approx(0.5, rel=0.002)
    assert song._coverage(fit, 100.0) == pytest.approx(1.0, abs=0.02)


def test_coverage_of_fast_halved_beats_stays_full() -> None:
    fit = fit_grid(_beats(280.0, 0.1, 400))
    assert fit.bpm == pytest.approx(140.0, rel=0.002)
    assert song._coverage(fit, 400 * 60.0 / 280.0) == pytest.approx(1.0, abs=0.02)


def test_coverage_of_sparse_detection_stays_low_and_warns() -> None:
    sparse = _beats(120.0, 0.08, 100)  # beats found in only the first half of a 100 s song
    fit = fit_grid(sparse)
    duration = 100.0
    assert song._coverage(fit, duration) < 0.6
    assert _confidence(fit, duration) < song.CONFIDENCE_WARN


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


# ---- analyze_song ------------------------------------------------------------------


def _write(tmp_path: Path, data: np.ndarray, name: str = "song.wav") -> Path:
    return write_wav(tmp_path / name, data, SAMPLE_RATE)


@pytest.fixture(scope="module")
def regular(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, song.SongAnalysis]:
    path = _write(tmp_path_factory.mktemp("regular"), click_track(120.0, 1.3, 30.0))
    return path, analyze_song(path)


def test_analysis_fields_for_a_known_click_track(regular: tuple[Path, song.SongAnalysis]) -> None:
    _, a = regular
    period = 0.5
    assert a.bpm == pytest.approx(120.0, rel=0.005)
    # The first downbeat is the louder click at 1.3 s, not the first beat of the grid.
    assert a.offset == pytest.approx(1.3, abs=0.03)
    assert 0 <= a.offset < 4 * period
    assert a.duration == pytest.approx(30.0, abs=0.05)
    assert a.confidence > 0.8
    assert a.residual_ms < 20
    assert a.warnings == []
    assert len(a.source_hash) == 64
    assert a.beats[0] < period
    assert a.beats[-1] > a.duration - period
    assert np.diff(a.beats) == pytest.approx(period, rel=0.01)
    assert np.diff(a.downbeats) == pytest.approx(4 * period, rel=0.01)
    assert a.downbeats[0] == a.offset or a.offset in a.downbeats
    assert set(a.downbeats) <= set(a.beats)


def test_downbeat_phase_follows_the_louder_kick(tmp_path: Path) -> None:
    for first in (0.08, 0.58, 1.08, 1.58):  # the louder click moves to each of the four phases
        times = [first + 0.5 * i for i in range(60)]
        gains = [1.0 if i % 4 == 0 else 0.5 for i in range(60)]
        a = analyze_song(_write(tmp_path, click_times(times, 30.0, gains=gains)))
        assert a.offset == pytest.approx(first, abs=0.03), first


def test_candidates_are_ascending_downbeats(regular: tuple[Path, song.SongAnalysis]) -> None:
    _, a = regular
    assert a.candidates == sorted(set(a.candidates))
    assert set(a.candidates) <= set(a.downbeats)
    assert all(0 < c < a.duration for c in a.candidates)


def test_energy_follows_a_sparse_then_dense_arrangement(tmp_path: Path) -> None:
    sparse = [0.08 + 2.0 * i for i in range(8)]  # one soft click per bar
    dense = [16.08 + 0.25 * i for i in range(64)]  # eighth notes, full level
    times = [*sparse, *dense]
    gains = [0.25] * len(sparse) + [1.0] * len(dense)
    a = analyze_song(_write(tmp_path, click_times(times, 32.0, gains=gains)))
    energy = np.asarray(a.energy)
    split = int(16.0 / a.hop)
    assert energy[split + 5 :].mean() > energy[: split - 5].mean() + 0.1


def test_energy_matches_hop_and_duration(regular: tuple[Path, song.SongAnalysis]) -> None:
    _, a = regular
    assert a.hop == 0.1
    assert len(a.energy) == int(a.duration / a.hop) + 1
    assert all(0.0 <= v <= 1.0 for v in a.energy)


def test_loose_and_drifting_beats_get_low_confidence(tmp_path: Path) -> None:
    loose = analyze_song(_write(tmp_path, click_track(120.0, 0.08, 30.0, jitter=0.15), "l.wav"))
    rng = np.random.default_rng(3)
    times = [0.3]
    while times[-1] < 30.0:
        times.append(times[-1] + float(rng.uniform(0.2, 0.8)))
    scattered = analyze_song(_write(tmp_path, click_times(times, 30.0), "s.wav"))
    drift = [0.3]
    while drift[-1] < 30.0:
        drift.append(drift[-1] + 60.0 / (100.0 + 15.0 * drift[-1] / 30.0))
    drifting = analyze_song(_write(tmp_path, click_times(drift, 30.0), "d.wav"))
    for a in (loose, scattered, drifting):
        assert a.confidence < 0.5
        assert any("拍点不稳" in w and "sections.json" not in w for w in a.warnings)


def test_analysis_is_deterministic(regular: tuple[Path, song.SongAnalysis]) -> None:
    path, first = regular
    again = analyze_song(path)
    assert json.dumps(first.to_document()) == json.dumps(again.to_document())


def test_document_is_rounded_json(regular: tuple[Path, song.SongAnalysis]) -> None:
    _, a = regular
    doc = a.to_document()
    assert set(doc) == {
        "source_hash", "duration", "bpm", "offset", "residual_ms", "confidence",
        "beats", "downbeats", "candidates", "hop", "energy", "warnings",
    }  # fmt: skip
    text = json.dumps(doc)
    assert json.loads(text) == doc
    for value in (doc["bpm"], doc["offset"], doc["confidence"], *doc["beats"], *doc["energy"]):
        assert round(value, 6) == value
