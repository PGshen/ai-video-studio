"""`animation_html` 项目的渲染任务与成片定稿（2B T4）：阶段名按项目流水线解析。"""

from __future__ import annotations

import json

import pytest

from fixtures.animation.seed import seed_animation_project
from fixtures.animation_html.seed import seed_animation_html_project
from studio.api.animation_stage import animation_stage_of
from studio.db.repo.snapshots import latest_snapshot
from studio.workspace import create_snapshot

from .conftest import ApiEnv, assert_detail


def _html_project(api_env: ApiEnv) -> str:
    return seed_animation_html_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )


def _write_final_json(api_env: ApiEnv, project_id: str, snapshot_id: str) -> None:
    output = api_env.workdir(project_id) / "output"
    output.mkdir(parents=True, exist_ok=True)
    (output / "final.json").write_text(
        json.dumps({"snapshot_id": snapshot_id, "engine": "html"}), encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"pipeline": ["topic", "narrative", "animation_html"]}, "animation_html"),
        ({"pipeline": ["topic", "narrative", "animation"]}, "animation"),
        ({"pipeline": ["concept", "beatsheet", "music", "animation_html"]}, "animation_html"),
        ({}, "animation"),
        ({"pipeline": "garbage"}, "animation"),
    ],
)
def test_animation_stage_is_read_from_the_project_pipeline(
    settings: dict[str, object], expected: str
) -> None:
    assert animation_stage_of(settings) == expected


async def test_html_project_can_queue_a_render_job(api_env: ApiEnv) -> None:
    pid = _html_project(api_env)
    response = await api_env.client.post(f"/api/projects/{pid}/render")
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "queued"


async def test_html_project_with_locked_animation_stage_cannot_render(api_env: ApiEnv) -> None:
    created = await api_env.client.post(
        "/api/projects", json={"title": "HTML", "video_kind": "explainer_html"}
    )
    assert created.status_code == 201, created.text
    response = await api_env.client.post(f"/api/projects/{created.json()['id']}/render")
    assert response.status_code == 409
    assert "动画" in assert_detail(response)


async def test_html_finalize_marks_animation_html_finalized_and_completes_the_project(
    api_env: ApiEnv,
) -> None:
    pid = _html_project(api_env)
    snapshot = latest_snapshot(api_env.app.state.engine, pid)
    assert snapshot is not None
    _write_final_json(api_env, pid, snapshot.id)

    response = await api_env.client.post(f"/api/projects/{pid}/animation/finalize-render")

    assert response.status_code == 200, response.text
    assert response.json()["stage"] == "animation_html"
    assert response.json()["status"] == "finalized"
    assert (await api_env.client.get(f"/api/projects/{pid}")).json()["completed_at"] is not None


async def test_html_finalize_rejects_changes_made_after_the_render(api_env: ApiEnv) -> None:
    pid = _html_project(api_env)
    snapshot = latest_snapshot(api_env.app.state.engine, pid)
    assert snapshot is not None
    _write_final_json(api_env, pid, snapshot.id)
    scenes = api_env.workdir(pid) / "animation" / "scenes"
    scenes.mkdir(parents=True, exist_ok=True)
    (scenes / "s-hook.js").write_text("module.exports = {};\n", encoding="utf-8")
    create_snapshot(api_env.app.state.engine, api_env.app.state.blobs, pid, reason="edit")

    response = await api_env.client.post(f"/api/projects/{pid}/animation/finalize-render")

    assert response.status_code == 409
    assert "重新渲染" in assert_detail(response)


async def test_manim_project_still_renders_and_finalizes_the_animation_stage(
    api_env: ApiEnv,
) -> None:
    pid = seed_animation_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    assert (await api_env.client.post(f"/api/projects/{pid}/render")).status_code == 201
    snapshot = latest_snapshot(api_env.app.state.engine, pid)
    assert snapshot is not None
    _write_final_json(api_env, pid, snapshot.id)
    response = await api_env.client.post(f"/api/projects/{pid}/animation/finalize-render")
    assert response.status_code == 200 and response.json()["stage"] == "animation"
