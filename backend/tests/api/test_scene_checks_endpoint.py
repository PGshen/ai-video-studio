"""`GET /api/projects/{id}/animation/scene-checks`（TD-33）：HTTP 层薄封装，
`compute_scene_checks` 本身的行为已经在 `test_scene_checks.py` 里覆盖过。
"""

from __future__ import annotations

from studio.db.repo.sessions import create_session
from studio.db.repo.snapshots import insert_snapshot
from studio.db.repo.turns import append_event, create_turn_if_session_idle, finish_turn

from .conftest import ApiEnv


async def _project(api_env: ApiEnv) -> str:
    body = await api_env.create_project()
    return body["id"]


class TestGetSceneChecks:
    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get(
            "/api/projects/does-not-exist/animation/scene-checks",
            params={"scene_id": ["s-hook"]},
        )

        assert response.status_code == 404

    async def test_never_checked_scene_reports_not_checked(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.get(
            f"/api/projects/{pid}/animation/scene-checks",
            params={"scene_id": ["s-hook"]},
        )

        assert response.status_code == 200
        assert response.json()["scenes"]["s-hook"] == {
            "validate_scenes": {"status": "not_checked", "stale": False, "checked_at": None},
            "render_preview": {"status": "not_checked", "stale": False, "checked_at": None},
        }

    async def test_passed_preview_is_reported(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        engine = api_env.app.state.engine
        session = create_session(
            engine,
            project_id=pid,
            stage="animation",
            model_profile_id="fake-profile",
            runtime="fake",
        )
        turn = create_turn_if_session_idle(engine, session.id, "嗯")
        assert turn is not None
        manifest = {"animation/scenes/s-hook.py": "sha-a"}
        append_event(
            engine,
            turn_id=turn.id,
            session_id=session.id,
            type="tool_call",
            payload={
                "turn_id": turn.id,
                "call_id": "c1",
                "name": "render_preview",
                "args": {"scene_id": "s-hook"},
            },
        )
        append_event(
            engine,
            turn_id=turn.id,
            session_id=session.id,
            type="tool_result",
            payload={"turn_id": turn.id, "call_id": "c1", "text": "ok", "is_error": False},
        )
        snapshot = insert_snapshot(engine, project_id=pid, manifest=manifest, reason="turn")
        finish_turn(
            engine,
            turn.id,
            status="done",
            end_snapshot_id=snapshot.id,
            usage=None,
            cost_usd=None,
            error=None,
            resume_ref=None,
        )

        response = await api_env.client.get(
            f"/api/projects/{pid}/animation/scene-checks",
            params={"scene_id": ["s-hook"]},
        )

        assert response.status_code == 200
        preview = response.json()["scenes"]["s-hook"]["render_preview"]
        assert preview["status"] == "passed"
        assert preview["stale"] is False
