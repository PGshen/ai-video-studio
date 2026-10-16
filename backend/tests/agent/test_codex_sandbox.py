"""codex 的 permission profile（codex-runtime T5；行为见 codex.md「沙箱与读隔离」）。"""

from __future__ import annotations

import tomllib
from pathlib import Path

from studio.agent.codex_sandbox import PROFILE_NAME, permission_args, sandbox_args
from studio.agent.exec_policy import codex_sandbox_available
from studio.agent.sandbox_paths import sensitive_home_dirs


def _overrides(args: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for flag, item in zip(args, args[1:], strict=False):
        if flag == "-c":
            key, _, raw = item.partition("=")
            out[key] = tomllib.loads(f"v = {raw}")["v"]
    return out


def _layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    data = repo / "data"
    workdir = data / "projects" / "p1"
    workdir.mkdir(parents=True)
    return repo, data, workdir, tmp_path / "home"


def test_profile_denies_repo_data_and_credentials_and_reopens_the_workspace(tmp_path: Path) -> None:
    repo, data, workdir, home = _layout(tmp_path)
    args = permission_args(workdir, repo, data, home=home)
    overrides = _overrides(args)

    assert "-s" not in args  # sandbox_mode and default_permissions are mutually exclusive
    assert overrides[f"permissions.{PROFILE_NAME}.extends"] == ":workspace"
    assert overrides["default_permissions"] == PROFILE_NAME
    filesystem = overrides[f"permissions.{PROFILE_NAME}.filesystem"]
    assert isinstance(filesystem, dict)
    assert filesystem[str(repo.resolve())] == "deny"
    assert filesystem[str(data.resolve())] == "deny"
    for path in sensitive_home_dirs(home):
        assert filesystem[str(path)] == "deny"
    assert filesystem[str(home.resolve() / ".codex")] == "deny"
    assert filesystem[str(workdir.resolve())] == "write"
    assert filesystem[":tmpdir"] == "read"
    assert filesystem[":slash_tmp"] == "read"


def test_paths_are_resolved(tmp_path: Path) -> None:
    repo, data, workdir, home = _layout(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(repo)
    filesystem = _overrides(
        permission_args(link / "data" / "projects" / "p1", link, link / "data", home=home)
    )[f"permissions.{PROFILE_NAME}.filesystem"]
    assert isinstance(filesystem, dict)
    assert filesystem[str(workdir.resolve())] == "write"
    assert str(link / "data") not in filesystem


def test_workspace_wins_when_it_is_also_a_denied_root(tmp_path: Path) -> None:
    # Brainstorm scratch dirs live under data_dir; a path listed twice keeps the write grant.
    repo, data, _, home = _layout(tmp_path)
    filesystem = _overrides(permission_args(data, repo, data, home=home))[
        f"permissions.{PROFILE_NAME}.filesystem"
    ]
    assert isinstance(filesystem, dict)
    assert filesystem[str(data.resolve())] == "write"


def test_sandbox_args_by_exec_mode(tmp_path: Path) -> None:
    repo, data, workdir, home = _layout(tmp_path)
    sandboxed = sandbox_args("sandboxed", workdir, repo, data, home=home)
    assert sandboxed == permission_args(workdir, repo, data, home=home)
    assert sandbox_args("unsandboxed", workdir, repo, data, home=home) == [
        "-s",
        "danger-full-access",
    ]
    assert sandbox_args("disabled", workdir, repo, data, home=home) is None


def test_network_opens_the_profile_network_only(tmp_path: Path) -> None:
    """open-mode 设计 §5.2：`permissions.<profile>.network.enabled=true`（2026-10-16 实测）。"""
    repo, data, workdir, home = _layout(tmp_path)
    offline = permission_args(workdir, repo, data, home=home)
    online = permission_args(workdir, repo, data, home=home, network=True)

    key = f"permissions.{PROFILE_NAME}.network.enabled"
    assert key not in _overrides(offline)
    assert _overrides(online)[key] is True
    assert {k: v for k, v in _overrides(online).items() if k != key} == _overrides(offline)
    assert sandbox_args("sandboxed", workdir, repo, data, home=home, network=True) == online
    assert sandbox_args("unsandboxed", workdir, repo, data, home=home, network=True) == [
        "-s",
        "danger-full-access",
    ]


def test_only_macos_has_a_verified_codex_sandbox() -> None:
    assert codex_sandbox_available("darwin")
    assert not codex_sandbox_available("win32")
    assert not codex_sandbox_available("linux")
