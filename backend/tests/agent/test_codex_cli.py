"""`codex_cli`：定位 ChatGPT 桌面版自带的 Codex CLI（codex-runtime T1）。"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from studio.agent.codex_cli import CodexVersionError, codex_version, desktop_candidates, find_codex


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _bundled(root: Path) -> Path:
    return root / "ChatGPT.app" / "Contents" / "Resources" / "codex-cli" / "bin" / "codex"


def test_desktop_candidates_on_macos(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert desktop_candidates(platform="darwin", home=home) == [
        _bundled(Path("/Applications")),
        _bundled(home / "Applications"),
    ]


def test_no_known_desktop_location_off_macos(tmp_path: Path) -> None:
    # Windows/Linux paths are unverified (ADR 0030 precondition 4): use STUDIO_CODEX_BIN there.
    assert desktop_candidates(platform="win32", home=tmp_path) == []
    assert desktop_candidates(platform="linux", home=tmp_path) == []


def test_override_wins_over_desktop_app(tmp_path: Path) -> None:
    override = _touch(tmp_path / "custom" / "codex")
    desktop = _touch(_bundled(tmp_path / "apps"))
    assert find_codex(override, [desktop]) == override


def test_missing_override_does_not_fall_back(tmp_path: Path) -> None:
    # A misspelt STUDIO_CODEX_BIN must not silently pick up another CLI.
    desktop = _touch(_bundled(tmp_path / "apps"))
    assert find_codex(tmp_path / "nope", [desktop]) is None


def test_first_existing_desktop_candidate(tmp_path: Path) -> None:
    missing = _bundled(tmp_path / "system")
    present = _touch(_bundled(tmp_path / "user"))
    assert find_codex(None, [missing, present]) == present


def test_not_installed(tmp_path: Path) -> None:
    assert find_codex(None, [_bundled(tmp_path)]) is None


@pytest.mark.skipif(sys.platform == "win32", reason="shell script stand-in")
async def test_codex_version_parses_cli_output(tmp_path: Path) -> None:
    fake = tmp_path / "codex"
    fake.write_text("#!/bin/sh\necho 'codex-cli 0.162.0-alpha.17.2'\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    assert await codex_version(fake) == "0.162.0-alpha.17.2"


@pytest.mark.skipif(sys.platform == "win32", reason="shell script stand-in")
async def test_codex_version_rejects_unexpected_output(tmp_path: Path) -> None:
    fake = tmp_path / "codex"
    fake.write_text("#!/bin/sh\necho 'something else'\nexit 3\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(CodexVersionError):
        await codex_version(fake)
