from __future__ import annotations

from pathlib import Path

import pytest

from studio.workspace.layout import project_dir


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    d = project_dir(tmp_path / "data", "proj-1")
    d.mkdir(parents=True)
    return d
