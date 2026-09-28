from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from studio.db.engine import make_engine, migrate
from studio.workspace.blobs import BlobStore
from studio.workspace.layout import project_dir


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = make_engine(tmp_path / "studio.db")
    migrate(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def blobs(data_dir: Path) -> BlobStore:
    return BlobStore(data_dir / "blobs")


@pytest.fixture
def project_id() -> str:
    return "proj-1"


@pytest.fixture
def workdir(data_dir: Path, project_id: str) -> Path:
    d = project_dir(data_dir, project_id)
    d.mkdir(parents=True)
    return d
