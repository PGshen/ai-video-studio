from __future__ import annotations

import sys
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from fixtures.narrative.seed import seed_narrative_project
from studio.db.engine import make_engine, migrate
from studio.workspace import BlobStore, project_dir

UTF8_MODE_HINT = (
    "Windows 上跑测试需要 Python 的 UTF-8 模式（否则文本 IO 默认按 GBK）："
    "用 `uv run --project backend python scripts/tasks.py check`，"
    "或者先 `$env:PYTHONUTF8=1` 再运行 pytest。"
)


def utf8_mode_problem(platform: str, utf8_mode: int) -> str | None:
    """Tests write and read text without naming the encoding; production code always names
    UTF-8 (lint + `test_lint_rules`). On Windows the default is the locale code page, so the
    suite must run in UTF-8 mode, which `tasks.py` turns on (design §7)."""
    if platform == "win32" and not utf8_mode:
        return UTF8_MODE_HINT
    return None


def pytest_configure(config: pytest.Config) -> None:
    problem = utf8_mode_problem(sys.platform, sys.flags.utf8_mode)
    if problem:
        raise pytest.UsageError(problem)


# ---- platform markers (windows-native plan T8) ----
#
# The only way to skip a test by platform. Each use names the reason, e.g.
# `@pytest.mark.posix_only("chmod 000 does not block reads on Windows")`; a test skipped on
# one platform must either have a counterpart covering that platform or the feature must not
# exist there. Never `xfail` instead.

_PLATFORM_MARKERS = {
    "posix_only": ("POSIX 才有的行为", lambda platform: platform != "win32"),
    "macos_only": ("只在 macOS 上存在", lambda platform: platform == "darwin"),
    "windows_only": ("只在 Windows 上存在", lambda platform: platform == "win32"),
}


def platform_skip_reason(marker: str, reason: str | None, platform: str) -> str | None:
    """Skip reason for a platform marker on `platform`, or `None` when the test runs.
    Raises `UsageError` when a platform marker has no reason."""
    spec = _PLATFORM_MARKERS.get(marker)
    if spec is None:
        return None
    if not reason or not reason.strip():
        raise pytest.UsageError(f"@pytest.mark.{marker} 必须写明原因")
    label, runs_on = spec
    return None if runs_on(platform) else f"{label}：{reason}"


_ERROR_PRIVILEGE_NOT_HELD = 1314
SYMLINK_HINT = "本机不能创建符号链接（Windows 请在 设置 → 系统 → 开发者选项 里打开开发者模式）"


def missing_symlink_privilege(exc: BaseException) -> bool:
    """Windows without Developer Mode refuses `os.symlink` with ERROR_PRIVILEGE_NOT_HELD."""
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) == _ERROR_PRIVILEGE_NOT_HELD


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, Any, None]:
    """Symlink tests guard the workspace against escapes; where symlinks cannot be created at
    all they are skipped with a hint instead of failing (plan T8). AC2 requires Developer Mode,
    so on the development machine they run."""
    outcome = yield
    report = outcome.get_result()
    if call.excinfo is not None and missing_symlink_privilege(call.excinfo.value):
        report.outcome = "skipped"
        report.longrepr = (str(item.path), item.location[1] or 0, f"Skipped: {SYMLINK_HINT}")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        for name in _PLATFORM_MARKERS:
            for mark in item.iter_markers(name):
                reason = mark.args[0] if mark.args else mark.kwargs.get("reason")
                skip = platform_skip_reason(name, reason, sys.platform)
                if skip is not None:
                    item.add_marker(pytest.mark.skip(reason=skip))


@pytest.fixture
def symlinks_supported(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Skip when this machine cannot create symlinks (Windows without Developer Mode).

    Symlink tests guard the workspace against escapes, so a skip here should be rare:
    turn on Developer Mode rather than accept it (windows-native plan, AC2).
    """
    probe = tmp_path_factory.mktemp("symlink-probe")
    try:
        (probe / "link").symlink_to(probe / "missing")
    except OSError as exc:
        pytest.skip(f"{SYMLINK_HINT}：{exc}")


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """每个测试前后清空 get_settings() 的缓存，避免用例间互相污染。"""
    from studio.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@dataclass
class NarrativeProjectEnv:
    """`seed_narrative_project` 建出的项目：选题已定稿，叙事阶段 `active`。

    供 T5/T6（`validate_narrative`/`synthesize_tts` 工具）、T8（端到端集成
    测试）复用。
    """

    data_dir: Path
    engine: Engine
    blobs: BlobStore
    project_id: str

    @property
    def workdir(self) -> Path:
        return project_dir(self.data_dir, self.project_id)


@pytest.fixture
def narrative_project(tmp_path: Path) -> Iterator[NarrativeProjectEnv]:
    data_dir = tmp_path / "data"
    engine = make_engine(tmp_path / "studio.db")
    migrate(engine)
    blobs = BlobStore(data_dir / "blobs")

    project_id = seed_narrative_project(engine, blobs, data_dir=data_dir)

    yield NarrativeProjectEnv(data_dir=data_dir, engine=engine, blobs=blobs, project_id=project_id)
    engine.dispose()
