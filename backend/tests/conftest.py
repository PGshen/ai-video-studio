from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import Engine

from fixtures.animation.seed import seed_animation_project
from studio.db.engine import make_engine, migrate
from studio.workspace import BlobStore, project_dir


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """每个测试前后清空 get_settings() 的缓存，避免用例间互相污染。"""
    from studio.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@dataclass
class AnimationProjectEnv:
    """`seed_animation_project` 建出的项目：叙事已定稿、动画阶段 `active`。

    供 T5（worker）、T7/T8（`validate_scenes`/`render_preview` 工具）、T14
    （端到端集成测试）复用，不用各自重新构造一遍叙事 fixture 数据。放在这个
    顶层 `conftest.py`（而不是 `tests/api/conftest.py`）是因为消费者跨越
    `tests/test_worker.py`、`tests/stages/`、`tests/api/` 好几个目录，
    pytest fixture 按目录树作用域生效，放在某个子目录的 conftest 里其它
    子目录用不到（决策记录 D12）。
    """

    data_dir: Path
    engine: Engine
    blobs: BlobStore
    project_id: str

    @property
    def workdir(self) -> Path:
        return project_dir(self.data_dir, self.project_id)


@pytest.fixture
def animation_project(tmp_path: Path) -> Iterator[AnimationProjectEnv]:
    data_dir = tmp_path / "data"
    engine = make_engine(tmp_path / "studio.db")
    migrate(engine)
    blobs = BlobStore(data_dir / "blobs")

    project_id = seed_animation_project(engine, blobs, data_dir=data_dir)

    yield AnimationProjectEnv(data_dir=data_dir, engine=engine, blobs=blobs, project_id=project_id)
    engine.dispose()
