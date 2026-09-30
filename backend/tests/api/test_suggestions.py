"""`/api/projects/{id}/suggestions*`、`/api/suggestions/{id}/{apply,dismiss}`（计划 M5 T9）。"""

from __future__ import annotations

from typing import Any

import pytest

from studio.agent.bus import SessionBus
from studio.api.sessions import WIRE_EVENT_TYPES, _stream_events
from studio.db.repo.suggestions import create_suggestion
from studio.db.repo.turns import append_event

from .conftest import ApiEnv


def _add(
    api_env: ApiEnv,
    project_id: str,
    *,
    from_stage: str = "animation",
    to_stage: str = "narrative",
    content: str = "s-hook 旁白太长",
) -> dict[str, Any]:
    value = create_suggestion(
        api_env.app.state.engine,
        project_id=project_id,
        from_stage=from_stage,
        to_stage=to_stage,
        content=content,
        turn_id="t1",
    )
    return {"id": value.id, "content": content}


class TestList:
    async def test_lists_a_projects_suggestions_oldest_first(self, api_env: ApiEnv) -> None:
        pid = (await api_env.create_project())["id"]
        first = _add(api_env, pid, content="第一条")
        second = _add(api_env, pid, content="第二条")
        _add(api_env, (await api_env.create_project())["id"], content="别的项目")

        response = await api_env.client.get(f"/api/projects/{pid}/suggestions")

        assert response.status_code == 200
        body = response.json()
        assert [s["id"] for s in body] == [first["id"], second["id"]]
        assert body[0] == {
            "id": first["id"],
            "project_id": pid,
            "from_stage": "animation",
            "to_stage": "narrative",
            "content": "第一条",
            "status": "open",
            "turn_id": "t1",
            "created_at": body[0]["created_at"],
        }

    async def test_filters_by_status(self, api_env: ApiEnv) -> None:
        pid = (await api_env.create_project())["id"]
        keep = _add(api_env, pid)
        done = _add(api_env, pid)
        await api_env.client.post(f"/api/suggestions/{done['id']}/apply")

        open_ = (await api_env.client.get(f"/api/projects/{pid}/suggestions?status=open")).json()
        applied = (
            await api_env.client.get(f"/api/projects/{pid}/suggestions?status=applied")
        ).json()

        assert [s["id"] for s in open_] == [keep["id"]]
        assert [s["id"] for s in applied] == [done["id"]]

    async def test_unknown_status_is_422(self, api_env: ApiEnv) -> None:
        pid = (await api_env.create_project())["id"]

        response = await api_env.client.get(f"/api/projects/{pid}/suggestions?status=nope")

        assert response.status_code == 422

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/projects/nope/suggestions")

        assert response.status_code == 404


class TestSummary:
    async def test_counts_open_suggestions_per_target_stage(self, api_env: ApiEnv) -> None:
        pid = (await api_env.create_project())["id"]
        _add(api_env, pid, to_stage="narrative")
        _add(api_env, pid, to_stage="narrative")
        _add(api_env, pid, from_stage="narrative", to_stage="topic")
        done = _add(api_env, pid, to_stage="narrative")
        await api_env.client.post(f"/api/suggestions/{done['id']}/dismiss")

        response = await api_env.client.get(f"/api/projects/{pid}/suggestions/summary")

        assert response.status_code == 200
        assert response.json() == {"narrative": 2, "topic": 1}

    async def test_empty_when_nothing_is_open(self, api_env: ApiEnv) -> None:
        pid = (await api_env.create_project())["id"]

        response = await api_env.client.get(f"/api/projects/{pid}/suggestions/summary")

        assert response.json() == {}

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/projects/nope/suggestions/summary")

        assert response.status_code == 404


class TestApplyAndDismiss:
    @pytest.mark.parametrize(("action", "status"), [("apply", "applied"), ("dismiss", "dismissed")])
    async def test_open_suggestion_changes_status(
        self, api_env: ApiEnv, action: str, status: str
    ) -> None:
        pid = (await api_env.create_project())["id"]
        suggestion = _add(api_env, pid)

        response = await api_env.client.post(f"/api/suggestions/{suggestion['id']}/{action}")

        assert response.status_code == 200
        assert response.json()["status"] == status
        assert response.json()["content"] == suggestion["content"]

    @pytest.mark.parametrize("first", ["apply", "dismiss"])
    @pytest.mark.parametrize("second", ["apply", "dismiss"])
    async def test_a_resolved_suggestion_is_409_and_keeps_its_status(
        self, api_env: ApiEnv, first: str, second: str
    ) -> None:
        pid = (await api_env.create_project())["id"]
        suggestion = _add(api_env, pid)
        await api_env.client.post(f"/api/suggestions/{suggestion['id']}/{first}")

        response = await api_env.client.post(f"/api/suggestions/{suggestion['id']}/{second}")

        assert response.status_code == 409
        listing = (await api_env.client.get(f"/api/projects/{pid}/suggestions")).json()
        assert listing[0]["status"] == {"apply": "applied", "dismiss": "dismissed"}[first]

    @pytest.mark.parametrize("action", ["apply", "dismiss"])
    async def test_unknown_suggestion_is_404(self, api_env: ApiEnv, action: str) -> None:
        response = await api_env.client.post(f"/api/suggestions/nope/{action}")

        assert response.status_code == 404


class TestSse:
    def test_suggestion_is_a_wire_event_type(self) -> None:
        assert "suggestion" in WIRE_EVENT_TYPES

    async def test_a_persisted_suggestion_event_is_replayed_on_the_stream(
        self, api_env: ApiEnv
    ) -> None:
        from studio.db.repo.profiles import get_model_profile
        from studio.db.repo.sessions import create_session

        engine = api_env.app.state.engine
        pid = (await api_env.create_project())["id"]
        profile = get_model_profile(engine, "fake")
        assert profile is not None
        session = create_session(
            engine, project_id=pid, stage="animation", model_profile_id=profile.id, runtime="fake"
        )
        append_event(
            engine,
            turn_id="t1",
            session_id=session.id,
            type="suggestion",
            payload={"suggestion_id": "s1", "to_stage": "narrative"},
        )

        gen = _stream_events(engine, SessionBus(), session.id, after_seq=0)
        first = await anext(gen)
        await gen.aclose()

        assert first["event"] == "suggestion"
