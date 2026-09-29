"""TurnRunner 的「无工作区」模式（计划 M4 T3、决策 D2）：`project_id is None` 的头脑风暴
会话没有快照、没有 `upstream/`、没有越界检查，cwd 是每轮重置的 scratch 目录。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from studio.agent import events, fake
from studio.agent.runner import SessionBusyError
from studio.agent.runtime import TurnContext, UserInput
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import SessionValue, create_session
from studio.db.repo.snapshots import list_snapshots
from studio.db.repo.turns import (
    create_turn_if_session_idle,
    get_turn,
    latest_turn,
    list_events,
    mark_turn_running,
)
from studio.stages.brainstorm import STAGE as BRAINSTORM
from studio.workspace import scratch_dir

from .conftest import StudioEnv
from .test_runner import Harness, _make_harness, _until


@pytest.fixture
def h(env: StudioEnv) -> Harness:
    env.registry.register(BRAINSTORM)
    return _make_harness(env)


def _running(h: Harness, session_id: str) -> bool:
    turn = latest_turn(h.env.engine, session_id)
    return turn is not None and turn.status == "running"


def _brainstorm_session(h: Harness, stage: str = "brainstorm") -> SessionValue:
    profile = get_model_profile(h.env.engine, "fake")
    assert profile is not None
    return create_session(
        h.env.engine,
        project_id=None,
        stage=stage,
        model_profile_id=profile.id,
        runtime="fake",
    )


class TestWorkspacelessTurn:
    async def test_turn_completes_without_snapshots_or_preamble(self, h: Harness) -> None:
        before = len(list_snapshots(h.env.engine, h.env.project_id))
        session = _brainstorm_session(h)

        turn = await h.run(session.id, [fake.say("想法来了")], text="聊聊排序")

        assert turn.status == "done"
        assert turn.start_snapshot_id is None
        assert turn.end_snapshot_id is None
        rows = list_events(h.env.engine, session.id)
        assert [r.type for r in rows] == ["text"]
        assert len(list_snapshots(h.env.engine, h.env.project_id)) == before
        ctx = h.contexts[0]
        assert ctx.project_id is None
        assert ctx.session_id == session.id
        assert ctx.stage == "brainstorm"
        assert ctx.user_input.text == "聊聊排序"  # no preamble
        assert ctx.write_scope.writable == [] and ctx.write_scope.tool_managed == []
        assert ctx.workdir == scratch_dir(h.env.data_dir, session.id)
        assert not ctx.workdir.exists()  # removed again when the turn finished

    async def test_scratch_is_reset_at_start_and_removed_at_end(self, h: Harness) -> None:
        session = _brainstorm_session(h)
        scratch = scratch_dir(h.env.data_dir, session.id)
        stale = scratch / "old" / "leftover.txt"
        stale.parent.mkdir(parents=True)
        stale.write_text("上一轮留下的", encoding="utf-8")

        class Probe:
            seen: bool | None = None

            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                Probe.seen = (ctx.workdir / "old").exists()
                (ctx.workdir / "note.txt").write_text("x", encoding="utf-8")
                yield events.TurnEnd(resume_ref=None, status="done")

        await h.run(session.id, Probe)
        assert Probe.seen is False  # reset before the turn started
        # 一轮里写进去的东西没有越界还原通知，且一轮结束后整个 scratch 被删除。
        assert not [r for r in list_events(h.env.engine, session.id) if r.type == "notice"]
        assert not scratch.exists()

    async def test_startup_recovery_removes_leftover_scratch(self, h: Harness) -> None:
        session = _brainstorm_session(h)
        leftover = scratch_dir(h.env.data_dir, session.id) / "crash.txt"
        leftover.parent.mkdir(parents=True)
        leftover.write_text("崩溃时遗留", encoding="utf-8")
        h.runner.recover_on_startup()
        assert not scratch_dir(h.env.data_dir, session.id).exists()

    async def test_failure_and_cancel_end_without_snapshot(self, h: Harness) -> None:
        session = _brainstorm_session(h)

        class Exploding:
            async def run_turn(self, ctx: TurnContext) -> AsyncIterator[events.AgentEvent]:
                yield events.TextBlock(text="写了一半")
                raise RuntimeError("网络断开")

        failed = await h.run(session.id, Exploding)
        assert failed.status == "failed" and "网络断开" in (failed.error or "")
        assert failed.end_snapshot_id is None
        assert [r.type for r in list_events(h.env.engine, session.id)][-1] == "error"

        h.scripts.append([fake.sleep(5)])
        turn_id = await h.runner.start_turn(session.id, UserInput(text="go"))
        await _until(lambda: _running(h, session.id))
        assert h.runner.cancel(turn_id) is True
        await asyncio.wait_for(h.runner.wait(turn_id), timeout=5)
        cancelled = get_turn(h.env.engine, turn_id)
        assert cancelled is not None and cancelled.status == "cancelled"
        assert cancelled.end_snapshot_id is None

    async def test_second_message_while_running_is_busy(self, h: Harness) -> None:
        session = _brainstorm_session(h)
        h.scripts.append([fake.sleep(5)])
        turn_id = await h.runner.start_turn(session.id, UserInput(text="1"))
        with pytest.raises(SessionBusyError):
            await h.runner.start_turn(session.id, UserInput(text="2"))
        h.runner.cancel(turn_id)
        await asyncio.wait_for(h.runner.wait(turn_id), timeout=5)


class TestScheduling:
    async def test_brainstorm_and_project_turns_do_not_block_each_other(self, h: Harness) -> None:
        project_session = h.session()
        h.scripts.append([fake.sleep(5)])
        project_turn = await h.runner.start_turn(project_session, UserInput(text="p"))
        await _until(lambda: h.runner.is_project_busy(h.env.project_id))

        brainstorm = _brainstorm_session(h)
        turn = await h.run(brainstorm.id, [fake.say("不受项目 turn 影响")])
        assert turn.status == "done"
        assert h.runner.is_project_busy(h.env.project_id)

        h.runner.cancel(project_turn)
        await asyncio.wait_for(h.runner.wait(project_turn), timeout=5)

    async def test_two_brainstorm_sessions_run_concurrently(self, h: Harness) -> None:
        first, second = _brainstorm_session(h), _brainstorm_session(h)
        h.scripts.append([fake.sleep(5)])
        t1 = await h.runner.start_turn(first.id, UserInput(text="a"))
        await _until(lambda: _running(h, first.id))
        turn = await h.run(second.id, [fake.say("并行")])
        assert turn.status == "done"
        h.runner.cancel(t1)
        await asyncio.wait_for(h.runner.wait(t1), timeout=5)

    async def test_global_concurrency_limit_still_applies(self, env: StudioEnv) -> None:
        env.registry.register(BRAINSTORM)
        h = _make_harness(env, max_concurrent_turns=1)
        first, second = _brainstorm_session(h), _brainstorm_session(h)
        h.scripts.append([fake.sleep(5)])
        t1 = await h.runner.start_turn(first.id, UserInput(text="a"))
        await _until(lambda: _running(h, first.id))
        h.scripts.append([fake.say("等我")])
        t2 = await h.runner.start_turn(second.id, UserInput(text="b"))
        await asyncio.sleep(0.05)
        queued = get_turn(h.env.engine, t2)
        assert queued is not None and queued.status == "queued"
        h.runner.cancel(t1)
        await asyncio.wait_for(h.runner.wait(t2), timeout=5)
        done = get_turn(h.env.engine, t2)
        assert done is not None and done.status == "done"


class TestGuards:
    async def test_project_stage_session_without_project_is_rejected(self, h: Harness) -> None:
        session = _brainstorm_session(h, stage="topic")
        with pytest.raises(ValueError, match="项目"):
            await h.runner.start_turn(session.id, UserInput(text="x"))

    async def test_brainstorm_session_with_project_is_rejected(self, h: Harness) -> None:
        profile = get_model_profile(h.env.engine, "fake")
        assert profile is not None
        session = create_session(
            h.env.engine,
            project_id=h.env.project_id,
            stage="brainstorm",
            model_profile_id=profile.id,
            runtime="fake",
        )
        with pytest.raises(ValueError, match="头脑风暴"):
            await h.runner.start_turn(session.id, UserInput(text="x"))


class TestRecovery:
    async def test_running_workspaceless_turn_becomes_interrupted(self, h: Harness) -> None:
        session = _brainstorm_session(h)
        turn = create_turn_if_session_idle(h.env.engine, session.id, "hi")
        assert turn is not None
        mark_turn_running(h.env.engine, turn.id, start_snapshot_id=None)

        h.runner.recover_on_startup()

        recovered = get_turn(h.env.engine, turn.id)
        assert recovered is not None
        assert recovered.status == "interrupted"
        assert recovered.end_snapshot_id is None
