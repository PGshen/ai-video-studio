"""One rule for "which file is the uploaded song" (TD-76): `find_sources` / `find_source`, and the
timeline loader's `_source_file` agreeing with them on the same directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from studio.stages.common.music_source import SOURCE_EXTENSIONS, find_source, find_sources
from studio.timeline.build import TimelineError
from studio.timeline.load import _source_file


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_the_extensions_are_the_upload_whitelist() -> None:
    assert SOURCE_EXTENSIONS == ("mp3", "wav", "m4a", "flac", "ogg")


def test_no_source_gives_an_empty_list(tmp_path: Path) -> None:
    assert find_sources(tmp_path / "music") == []  # the directory does not even exist
    (tmp_path / "music").mkdir()
    _touch(tmp_path / "music" / "source.txt")  # not a whitelisted extension
    (tmp_path / "music" / "source.ogg").mkdir()  # not a regular file
    assert find_sources(tmp_path / "music") == []
    assert find_source(tmp_path / "music") is None


def test_several_sources_are_listed_in_extension_order(tmp_path: Path) -> None:
    music = tmp_path / "music"
    wav = _touch(music / "source.wav")
    mp3 = _touch(music / "source.mp3")
    flac = _touch(music / "source.flac")
    assert find_sources(music) == [mp3, wav, flac]
    assert find_source(music) == mp3


def test_a_symlink_to_a_file_outside_is_not_a_source(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = _touch(tmp_path_factory.mktemp("outside") / "song.wav")
    music = tmp_path / "music"
    music.mkdir()
    (music / "source.wav").symlink_to(outside)
    assert find_sources(music) == []
    assert find_source(music) is None


@pytest.mark.parametrize(
    "layout",
    [
        [],
        ["source.wav"],
        ["source.mp3", "source.wav"],
        ["source.txt"],
        ["source.flac", "source.txt"],
        ["link:source.wav"],
        ["link:source.wav", "source.mp3"],
    ],
)
def test_the_timeline_and_find_source_agree(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory, layout: list[str]
) -> None:
    root = tmp_path / "ws"
    music = root / "music"
    music.mkdir(parents=True)
    outside = _touch(tmp_path_factory.mktemp("outside") / "song.wav")
    for entry in layout:
        if entry.startswith("link:"):
            (music / entry.removeprefix("link:")).symlink_to(outside)
        else:
            _touch(music / entry)
    sources = find_sources(music)
    if len(sources) == 1:
        assert _source_file(root, "") == f"music/{sources[0].name}"
        assert find_source(music) == sources[0]
        return
    with pytest.raises(TimelineError) as info:
        _source_file(root, "")
    if sources:
        assert "有多个音乐源文件" in str(info.value)
        assert all(path.name in str(info.value) for path in sources)
    else:
        assert "不存在" in str(info.value)
        assert find_source(music) is None


def test_the_timeline_reads_upstream_sources_with_the_same_rule(tmp_path: Path) -> None:
    _touch(tmp_path / "upstream" / "music" / "source.m4a")
    _touch(tmp_path / "upstream" / "music" / "source.doc")
    assert _source_file(tmp_path, "upstream/") == "music/source.m4a"
