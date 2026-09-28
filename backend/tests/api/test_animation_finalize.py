"""`POST /api/projects/{id}/animation/finalize-render`（任务简报 T11）。

"成片定稿"：`output/final.json` 记录的快照要和当前最新快照一致才能定稿——
不一致说明渲染之后工作区又发生了改动，成片没有覆盖这些改动，拒绝定稿并
提示重新渲染（计划 T11 小节的接口约定）。一致时把动画阶段标记 `finalized`，
并把项目标记完成（`completed_at` 不再是 `None`）。
"""

from __future__ import annotations

import json

from fixtures.animation.seed import seed_animation_project
from studio.db.repo.snapshots import latest_snapshot
from studio.workspace import create_snapshot

from .conftest import ApiEnv, assert_detail


async def _animation_project(api_env: ApiEnv) -> str:
    """叙事已定稿、动画阶段 `active` 的项目（复用 T4 的种子脚本，绕过 M3）。"""
    return seed_animation_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )


def _write_final_json(api_env: ApiEnv, project_id: str, *, snapshot_id: str) -> None:
    output_dir = api_env.workdir(project_id) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "snapshot_id": snapshot_id,
        "scene_hashes": {},
        "rendered_at": "2026-09-29T00:00:00+00:00",
    }
    (output_dir / "final.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


class TestFinalizeRender:
    async def test_missing_final_json_is_4xx(self, api_env: ApiEnv) -> None:
        pid = await _animation_project(api_env)

        response = await api_env.client.post(f"/api/projects/{pid}/animation/finalize-render")

        assert 400 <= response.status_code < 500
        assert_detail(response)

    async def test_stale_snapshot_is_4xx(self, api_env: ApiEnv) -> None:
        pid = await _animation_project(api_env)
        engine = api_env.app.state.engine
        blobs = api_env.app.state.blobs

        rendered = latest_snapshot(engine, pid)
        assert rendered is not None
        _write_final_json(api_env, pid, snapshot_id=rendered.id)

        # 模拟渲染之后工作区又有新的改动（还没被下一次渲染纳入成片）。
        workdir = api_env.workdir(pid)
        scenes_dir = workdir / "animation" / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)
        (scenes_dir / "s-hook.py").write_text("# edited after render\n", encoding="utf-8")
        create_snapshot(engine, blobs, pid, reason="test_edit_after_render")

        response = await api_env.client.post(f"/api/projects/{pid}/animation/finalize-render")

        assert response.status_code == 409
        assert "重新渲染" in assert_detail(response)

    async def test_matching_snapshot_finalizes_stage_and_completes_project(
        self, api_env: ApiEnv
    ) -> None:
        pid = await _animation_project(api_env)
        engine = api_env.app.state.engine

        rendered = latest_snapshot(engine, pid)
        assert rendered is not None
        _write_final_json(api_env, pid, snapshot_id=rendered.id)

        response = await api_env.client.post(f"/api/projects/{pid}/animation/finalize-render")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "finalized"
        assert body["finalized_snapshot_id"] == rendered.id

        project_response = await api_env.client.get(f"/api/projects/{pid}")
        assert project_response.json()["completed_at"] is not None

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post(
            "/api/projects/does-not-exist/animation/finalize-render"
        )

        assert response.status_code == 404
