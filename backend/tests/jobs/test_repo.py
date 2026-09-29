from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from studio.db.engine import session_scope
from studio.db.models import Job
from studio.jobs import (
    claim_next,
    complete,
    create_job,
    fail,
    get_job,
    heartbeat,
    list_jobs,
    reap_stale_running,
    update_progress,
)


def _backdate_heartbeat(engine: Engine, job_id: str, seconds_ago: float) -> None:
    with session_scope(engine) as db:
        row = db.get(Job, job_id)
        assert row is not None
        row.heartbeat_at = datetime.now(UTC) - timedelta(seconds=seconds_ago)


def test_claim_next_claims_once_then_queue_is_empty(migrated_engine: Engine):
    created = create_job(migrated_engine, type="final_render", project_id="proj-1", payload={})

    claimed = claim_next(migrated_engine, type="final_render")
    assert claimed is not None
    assert claimed.id == created.id
    assert claimed.status == "running"
    assert claimed.heartbeat_at is not None

    assert claim_next(migrated_engine, type="final_render") is None


def test_claim_next_ignores_jobs_of_a_different_type(migrated_engine: Engine):
    create_job(migrated_engine, type="preview", project_id="proj-1", payload={})

    assert claim_next(migrated_engine, type="final_render") is None


def test_heartbeat_and_update_progress_update_fields(migrated_engine: Engine):
    job = create_job(migrated_engine, type="final_render", project_id="proj-1", payload={})

    update_progress(migrated_engine, job.id, 0.5)
    heartbeat(migrated_engine, job.id)

    row = get_job(migrated_engine, job.id)
    assert row is not None
    assert row.progress == 0.5
    assert row.heartbeat_at is not None


def test_complete_marks_done_with_result(migrated_engine: Engine):
    job = create_job(migrated_engine, type="final_render", project_id="proj-1", payload={})

    result = complete(migrated_engine, job.id, result={"output_path": "output/final.mp4"})

    assert result.status == "done"
    assert result.progress == 1.0
    assert result.result == {"output_path": "output/final.mp4"}


def test_fail_marks_failed_with_error(migrated_engine: Engine):
    job = create_job(migrated_engine, type="final_render", project_id="proj-1", payload={})

    result = fail(migrated_engine, job.id, error="scene 1: RuntimeError")

    assert result.status == "failed"
    assert result.error == "scene 1: RuntimeError"


def test_list_jobs_filters_by_project_and_type(migrated_engine: Engine):
    create_job(migrated_engine, type="final_render", project_id="proj-1", payload={})
    create_job(migrated_engine, type="preview", project_id="proj-1", payload={})
    create_job(migrated_engine, type="final_render", project_id="proj-2", payload={})

    proj1_jobs = list_jobs(migrated_engine, "proj-1")
    assert {j.type for j in proj1_jobs} == {"final_render", "preview"}

    proj1_render_jobs = list_jobs(migrated_engine, "proj-1", type="final_render")
    assert len(proj1_render_jobs) == 1
    assert proj1_render_jobs[0].project_id == "proj-1"


def test_reap_stale_running_only_affects_expired_heartbeats(migrated_engine: Engine):
    stale_job = create_job(migrated_engine, type="final_render", project_id="proj-1", payload={})
    fresh_job = create_job(migrated_engine, type="final_render", project_id="proj-1", payload={})
    claim_next(migrated_engine, type="final_render")  # 领到 stale_job
    claim_next(migrated_engine, type="final_render")  # 领到 fresh_job
    _backdate_heartbeat(migrated_engine, stale_job.id, seconds_ago=120)

    reaped = reap_stale_running(migrated_engine, type="final_render", heartbeat_timeout_seconds=60)

    assert [job.id for job in reaped] == [stale_job.id]
    stale_row = get_job(migrated_engine, stale_job.id)
    fresh_row = get_job(migrated_engine, fresh_job.id)
    assert stale_row is not None
    assert fresh_row is not None
    assert stale_row.status == "failed"
    assert fresh_row.status == "running"
