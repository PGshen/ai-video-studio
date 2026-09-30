"""TD-27: home-directory locations that both sandboxes refuse to read."""

from __future__ import annotations

from pathlib import Path

from studio.agent.claude_scope import sandbox_settings
from studio.agent.sandbox_paths import sensitive_home_dirs


def test_sensitive_home_dirs_are_under_the_given_home(tmp_path: Path) -> None:
    dirs = sensitive_home_dirs(tmp_path)

    names = {d.relative_to(tmp_path).as_posix() for d in dirs}
    assert {".ssh", ".aws", ".gnupg", ".kube", ".docker", "Library/Keychains"} <= names
    assert all(d.is_absolute() for d in dirs)


def test_claude_sandbox_denies_sensitive_home_dirs(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = tmp_path / "repo" / "data" / "projects" / "p1"
    workdir.mkdir(parents=True)

    deny = sandbox_settings(workdir, tmp_path / "repo", tmp_path / "repo" / "data", home=home)[
        "filesystem"
    ]["denyRead"]

    for path in sensitive_home_dirs(home):
        assert str(path) in deny
    assert str((tmp_path / "repo").resolve()) in deny
