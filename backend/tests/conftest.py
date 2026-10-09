from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

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
