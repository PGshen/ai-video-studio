"""`studio.worker` 主循环（M2 T5）：队列处理与 Manim 下线（ADR 0027）。

HTML 渲染路径见 `test_worker_html.py`、`test_worker_html_music.py`。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine

from fixtures.animation.seed import seed_legacy_manim_project
from studio.db.engine import make_engine, migrate, session_scope
from studio.db.models import Job
from studio.jobs import claim_next, create_job, get_job
from studio.worker import MANIM_RETIRED_ERROR, run_once
from studio.workspace import BlobStore


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[Engine, BlobStore, Path]]:
    data_dir = tmp_path / "data"
    engine = make_engine(tmp_path / "studio.db")
    migrate(engine)
    yield engine, BlobStore(data_dir / "blobs"), data_dir
    engine.dispose()


def _backdate_heartbeat(engine: Engine, job_id: str, seconds_ago: float) -> None:
    with session_scope(engine) as db:
        row = db.get(Job, job_id)
        assert row is not None
        row.heartbeat_at = datetime.now(UTC) - timedelta(seconds=seconds_ago)


async def test_returns_false_when_queue_is_empty(env: tuple[Engine, BlobStore, Path]) -> None:
    engine, blobs, data_dir = env

    assert await run_once(engine, blobs, data_dir=data_dir) is False


async def test_reaps_stale_running_job_before_claiming_next(
    env: tuple[Engine, BlobStore, Path],
) -> None:
    engine, blobs, data_dir = env
    project_id = seed_legacy_manim_project(engine, blobs, data_dir=data_dir)
    stale = create_job(engine, type="final_render", project_id=project_id, payload={})
    # Another worker claimed it, then its heartbeat expired.
    claim_next(engine, type="final_render")
    _backdate_heartbeat(engine, stale.id, seconds_ago=999)

    claimed = await run_once(engine, blobs, data_dir=data_dir)

    assert claimed is False
    reaped = get_job(engine, stale.id)
    assert reaped is not None
    assert reaped.status == "failed"


async def test_legacy_manim_project_job_fails_with_retired_reason(
    env: tuple[Engine, BlobStore, Path],
) -> None:
    engine, blobs, data_dir = env
    project_id = seed_legacy_manim_project(engine, blobs, data_dir=data_dir)
    job = create_job(engine, type="final_render", project_id=project_id, payload={})

    assert await run_once(engine, blobs, data_dir=data_dir) is True

    failed = get_job(engine, job.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error == MANIM_RETIRED_ERROR
    assert not (data_dir / "projects" / project_id / "output" / "final.mp4").exists()
