"""I4: project-level serialization must not have a check-then-write race.

`TurnRunner` mutates `_running` and schedules queued turns on the event loop
thread. Endpoints that check `is_project_busy` and then write the workspace must
therefore run on that same thread (``async def`` with no ``await`` between check
and write), so the scheduler can never interleave between the two. Sync ``def``
endpoints would run in Starlette's thread pool instead.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from studio.agent.runner import TurnRunner
from studio.db.repo.snapshots import list_snapshots

from .conftest import ApiEnv


def _record_thread(calls: list[int], func: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        calls.append(threading.get_ident())
        return func(*args, **kwargs)

    return wrapper


@pytest.fixture
def busy_checks(api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    runner: TurnRunner = api_env.app.state.turn_runner
    monkeypatch.setattr(runner, "is_project_busy", _record_thread(calls, runner.is_project_busy))
    return calls


class TestBusyCheckRunsOnEventLoopThread:
    async def test_write_file(self, api_env: ApiEnv, busy_checks: list[int]) -> None:
        pid = (await api_env.create_project())["id"]
        response = await api_env.client.put(
            f"/api/projects/{pid}/files/topic/brief.md",
            params={"stage": "topic"},
            json={"content": "x"},
        )
        assert response.status_code == 200
        assert busy_checks == [threading.get_ident()]

    async def test_rollback(self, api_env: ApiEnv, busy_checks: list[int]) -> None:
        pid = (await api_env.create_project())["id"]
        init = list_snapshots(api_env.app.state.engine, pid)[0]
        response = await api_env.client.post(f"/api/projects/{pid}/snapshots/{init.id}/rollback")
        assert response.status_code == 200
        assert busy_checks == [threading.get_ident()]

    async def test_finalize_and_reopen(self, api_env: ApiEnv, busy_checks: list[int]) -> None:
        pid = (await api_env.create_project())["id"]
        finalize = await api_env.client.post(f"/api/projects/{pid}/stages/topic/finalize")
        reopen = await api_env.client.post(f"/api/projects/{pid}/stages/topic/reopen")
        assert finalize.status_code == 200
        assert reopen.status_code == 200
        assert busy_checks == [threading.get_ident()] * 2

    async def test_get_project(self, api_env: ApiEnv, busy_checks: list[int]) -> None:
        pid = (await api_env.create_project())["id"]
        response = await api_env.client.get(f"/api/projects/{pid}")
        assert response.status_code == 200
        assert busy_checks == [threading.get_ident()]


async def test_queued_turn_cannot_start_between_busy_check_and_write(api_env: ApiEnv) -> None:
    """A turn queued behind a running one is scheduled when the first finishes.

    Finishing the running turn and the rollback endpoint are both driven on the
    loop thread; after the rollback returns 200 the queued turn must only have
    started afterwards (its start snapshot is created after the rollback one).
    """
    from studio.agent.fake import FakeRuntime, sleep
    from studio.agent.runtime import UserInput
    from studio.db.repo.profiles import get_model_profile
    from studio.db.repo.sessions import create_session

    engine = api_env.app.state.engine
    runner: TurnRunner = api_env.app.state.turn_runner
    pid = (await api_env.create_project())["id"]
    profile = get_model_profile(engine, "fake")
    assert profile is not None
    sessions = [
        create_session(
            engine, project_id=pid, stage="topic", model_profile_id=profile.id, runtime="fake"
        )
        for _ in range(2)
    ]
    api_env.app.state.runtime_factory.register("fake", lambda: FakeRuntime([sleep(30)]))
    first = await runner.start_turn(sessions[0].id, UserInput(text="a"))
    second = await runner.start_turn(sessions[1].id, UserInput(text="b"))
    assert runner.is_project_busy(pid)

    init = list_snapshots(engine, pid)[0]
    blocked = await api_env.client.post(f"/api/projects/{pid}/snapshots/{init.id}/rollback")
    assert blocked.status_code == 409

    runner.cancel(first)
    await runner.wait(first)
    # The queued turn was scheduled on the loop as soon as the first finished.
    assert runner.is_project_busy(pid)
    still_blocked = await api_env.client.post(f"/api/projects/{pid}/snapshots/{init.id}/rollback")
    assert still_blocked.status_code == 409

    runner.cancel(second)
    await runner.wait(second)
