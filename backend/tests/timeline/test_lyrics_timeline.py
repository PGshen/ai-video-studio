"""Lyrics in the MV timeline (mv-lyrics design §3.2): loading, range clipping, hashing."""

from __future__ import annotations

from pathlib import Path

import pytest

from fixtures.import_music import write_mv_workspace
from studio.timeline.build import TimelineError
from studio.timeline.load import TimelineSources, load_timeline
from studio.timeline.lyrics import LYRICS_PATH

LRC = "[00:02.00]一\n[00:06.00]二\n[00:10.00]三\n[00:16.00]四\n"


def _load(root: Path):
    return load_timeline(
        TimelineSources(root, narration=False, music_source="import", produce=True)
    )


def _write_lrc(root: Path, text: str) -> None:
    (root / LYRICS_PATH).write_text(text, encoding="utf-8")


def _lines(root: Path) -> list[tuple[str, float, float]]:
    return [(item.text, item.start, item.end) for item in _load(root).timeline.lyrics]


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    write_mv_workspace(tmp_path)
    return tmp_path


def test_without_a_lyrics_file_the_timeline_has_no_lyrics_and_the_same_hash(workdir: Path) -> None:
    before = _load(workdir)
    assert before.timeline.lyrics == []
    _write_lrc(workdir, LRC)
    assert _load(workdir).hash != before.hash
    (workdir / LYRICS_PATH).unlink()
    assert _load(workdir).hash == before.hash


def test_lyrics_are_loaded_in_song_time(workdir: Path) -> None:
    _write_lrc(workdir, LRC)
    assert _lines(workdir) == [
        ("一", 2.0, 6.0),
        ("二", 6.0, 10.0),
        ("三", 10.0, 16.0),
        ("四", 16.0, 20.0),
    ]


def test_a_changed_lyric_changes_the_hash(workdir: Path) -> None:
    _write_lrc(workdir, LRC)
    first = _load(workdir).hash
    _write_lrc(workdir, LRC.replace("二", "贰"))
    assert _load(workdir).hash != first


def test_a_range_shifts_clips_and_drops_lines(tmp_path: Path) -> None:
    write_mv_workspace(tmp_path, range_=(4.5, 14.5))
    _write_lrc(tmp_path, LRC)
    # 一 (2–6) is clipped to the range start, 二 (6–10) shifts, 三 (10–16) is clipped at the end,
    # 四 (16–20) is outside.
    assert _lines(tmp_path) == [("一", 0.0, 1.5), ("二", 1.5, 5.5), ("三", 5.5, 10.0)]


def test_lyrics_entirely_outside_the_range_are_empty_not_an_error(tmp_path: Path) -> None:
    write_mv_workspace(tmp_path, range_=(17.0, 19.0))
    _write_lrc(tmp_path, "[00:01.00]早\n[00:03.00]也早\n[00:05.00]\n")
    assert _lines(tmp_path) == []


def test_a_broken_lyrics_file_is_reported_by_name(workdir: Path) -> None:
    _write_lrc(workdir, "没有时间戳的歌词")
    with pytest.raises(TimelineError, match="music/lyrics.lrc"):
        _load(workdir)


def test_a_lyrics_file_outside_the_workspace_is_refused(workdir: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "x.lrc"
    outside.write_text(LRC, encoding="utf-8")
    (workdir / LYRICS_PATH).symlink_to(outside)
    with pytest.raises(TimelineError, match="工作区之外"):
        _load(workdir)
