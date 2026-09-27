"""`/api/projects/{id}/snapshots*`（任务简报 T7）。"""

from __future__ import annotations

from studio.db.repo.snapshots import list_snapshots

from .conftest import ApiEnv, assert_detail


async def _project(api_env: ApiEnv) -> str:
    body = await api_env.create_project()
    return body["id"]


class TestListSnapshots:
    async def test_lists_init_snapshot(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.get(f"/api/projects/{pid}/snapshots")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["reason"] == "init"

    async def test_unknown_project_is_404(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/projects/does-not-exist/snapshots")
        assert response.status_code == 404


class TestDiff:
    async def test_diff_between_two_snapshots(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        init = list_snapshots(api_env.app.state.engine, pid)[0]
        await api_env.client.put(
            f"/api/projects/{pid}/files/topic/brief.md",
            params={"stage": "topic"},
            json={"content": "v1"},
        )
        from studio.workspace import create_snapshot

        engine, blobs = api_env.app.state.engine, api_env.app.state.blobs
        second = create_snapshot(engine, blobs, pid, "user_edit")

        response = await api_env.client.get(
            f"/api/projects/{pid}/snapshots/diff",
            params={"from": init.id, "to": second.id},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["added"] == ["topic/brief.md"]
        assert body["removed"] == []
        assert body["modified"] == []

    async def test_unknown_snapshot_is_404(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        init = list_snapshots(api_env.app.state.engine, pid)[0]

        response = await api_env.client.get(
            f"/api/projects/{pid}/snapshots/diff",
            params={"from": init.id, "to": "does-not-exist"},
        )

        assert response.status_code == 404
        assert_detail(response)


class TestRollback:
    async def test_rollback_restores_manifest_and_creates_new_snapshot(
        self, api_env: ApiEnv
    ) -> None:
        from studio.workspace import create_snapshot

        pid = await _project(api_env)
        init = list_snapshots(api_env.app.state.engine, pid)[0]
        await api_env.client.put(
            f"/api/projects/{pid}/files/topic/brief.md",
            params={"stage": "topic"},
            json={"content": "v1"},
        )
        # A snapshot capturing the write, so rolling back to `init` (an older
        # snapshot) actually differs from the latest one and produces a new
        # `reason=rollback` row instead of deduping to an identical manifest.
        create_snapshot(api_env.app.state.engine, api_env.app.state.blobs, pid, "user_edit")

        response = await api_env.client.post(f"/api/projects/{pid}/snapshots/{init.id}/rollback")

        assert response.status_code == 200
        assert response.json()["reason"] == "rollback"
        assert not (api_env.workdir(pid) / "topic" / "brief.md").exists()

    async def test_unknown_snapshot_is_404(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)

        response = await api_env.client.post(
            f"/api/projects/{pid}/snapshots/does-not-exist/rollback"
        )

        assert response.status_code == 404

    async def test_busy_project_is_409(self, api_env: ApiEnv) -> None:
        pid = await _project(api_env)
        init = list_snapshots(api_env.app.state.engine, pid)[0]
        turn_id = await api_env.make_busy(pid)

        response = await api_env.client.post(f"/api/projects/{pid}/snapshots/{init.id}/rollback")

        assert response.status_code == 409
        await api_env.release_busy(turn_id)
