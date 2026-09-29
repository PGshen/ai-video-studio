from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from studio.db.engine import make_engine, migrate


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "studio.db"


@pytest.fixture
def engine(db_path: Path) -> Iterator[Engine]:
    eng = make_engine(db_path)
    yield eng
    eng.dispose()


@pytest.fixture
def migrated_engine(engine: Engine) -> Engine:
    migrate(engine)
    return engine


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    path = tmp_path / "workdir"
    path.mkdir()
    return path
