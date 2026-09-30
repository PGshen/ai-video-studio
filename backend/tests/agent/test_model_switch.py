"""会话内换模型（计划 M5 T7，决策 D3）：TurnRunner 每轮按会话**当前**的配置运行；
换了之后的第一轮向会话推一条 `notice`；`turns.usage` 记录每一轮实际用的模型。
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import update

from studio.agent import fake
from studio.agent.fake import FakeRuntime, sleep
from studio.agent.runtime import UserInput
from studio.db.engine import session_scope
from studio.db.models import ModelProfile, Turn
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session, set_session_model_if_idle
from studio.db.repo.turns import (
    create_turn_if_session_idle,
    finish_turn,
    get_turn,
    list_events,
    mark_turn_running,
    previous_run_profile_name,
    record_run_profile,
)
from studio.stages.brainstorm import STAGE as BRAINSTORM

from .conftest import StudioEnv
from .test_runner import Harness, _make_harness, _never, _until

MODEL_SWITCHED = "model_switched"


def _add_profile(env: StudioEnv, name: str, **fields: Any) -> str:
    with session_scope(env.engine) as db:
        row = ModelProfile(
            name=name, provider="fake", model=f"{name}-model", runtime="fake", **fields
        )
        db.add(row)
        db.flush()
        return row.id


def _switch(h: Harness, session_id: str, profile_id: str) -> None:
    assert set_session_model_if_idle(h.env.engine, session_id, profile_id) is not None


def _notices(h: Harness, session_id: str) -> list[dict[str, Any]]:
    return [
        e.payload
        for e in list_events(h.env.engine, session_id)
        if e.type == "notice" and e.payload.get("kind") == MODEL_SWITCHED
    ]


async def test_usage_records_the_model_and_profile_of_every_turn(env: StudioEnv) -> None:
    h = _make_harness(env)
    session = h.session()

    turn = await h.run(session, [fake.say("x")])

    assert turn.usage is not None
    assert turn.usage["profile_name"] == "fake"
    assert turn.usage["model"] == "fake"


async def test_next_turn_runs_with_the_new_profile_and_its_budget(env: StudioEnv) -> None:
    h = _make_harness(env)
    session = h.session()
    await h.run(session, [fake.say("a")])
    other = _add_profile(env, "fake-b", max_steps_per_turn=7, max_cost_per_turn=0.5)

    _switch(h, session, other)
    turn = await h.run(session, [fake.say("b")])

    ctx = h.contexts[-1]
    assert ctx.model_profile.name == "fake-b"
    assert ctx.budget.max_steps == 7
    assert ctx.budget.max_cost_usd == 0.5
    assert turn.usage is not None
    assert (turn.usage["profile_name"], turn.usage["model"]) == ("fake-b", "fake-b-model")


async def test_first_turn_after_a_switch_gets_exactly_one_notice(env: StudioEnv) -> None:
    h = _make_harness(env)
    session = h.session()
    first = await h.run(session, [fake.say("a")])
    assert _notices(h, session) == []
    _switch(h, session, _add_profile(env, "fake-b"))

    second = await h.run(session, [fake.say("b")])
    third = await h.run(session, [fake.say("c")])

    notices = _notices(h, session)
    assert len(notices) == 1
    assert notices[0]["from"] == "fake" and notices[0]["to"] == "fake-b"
    assert "fake" in notices[0]["message"] and "fake-b" in notices[0]["message"]
    turn_ids = {
        e.turn_id
        for e in list_events(env.engine, session)
        if e.type == "notice" and e.payload.get("kind") == MODEL_SWITCHED
    }
    assert turn_ids == {second.id}
    assert first.id != second.id != third.id


async def test_no_notice_when_the_profile_did_not_change(env: StudioEnv) -> None:
    h = _make_harness(env)
    session = h.session()
    fake_id = get_model_profile(env.engine, "fake")
    assert fake_id is not None

    await h.run(session, [fake.say("a")])
    _switch(h, session, fake_id.id)  # 换成同一个
    await h.run(session, [fake.say("b")])

    assert _notices(h, session) == []


async def test_switching_back_and_forth_notices_each_time(env: StudioEnv) -> None:
    h = _make_harness(env)
    session = h.session()
    fake_id = get_model_profile(env.engine, "fake")
    assert fake_id is not None
    other = _add_profile(env, "fake-b")
    await h.run(session, [fake.say("a")])

    _switch(h, session, other)
    await h.run(session, [fake.say("b")])
    _switch(h, session, fake_id.id)
    await h.run(session, [fake.say("c")])

    assert [(n["from"], n["to"]) for n in _notices(h, session)] == [
        ("fake", "fake-b"),
        ("fake-b", "fake"),
    ]


async def test_switching_twice_before_the_next_turn_compares_with_the_last_run(
    env: StudioEnv,
) -> None:
    h = _make_harness(env)
    session = h.session()
    fake_id = get_model_profile(env.engine, "fake")
    assert fake_id is not None
    await h.run(session, [fake.say("a")])

    _switch(h, session, _add_profile(env, "fake-b"))
    _switch(h, session, fake_id.id)  # 又换回去：和上一轮实际用的一样
    await h.run(session, [fake.say("b")])

    assert _notices(h, session) == []


async def test_turns_recorded_before_this_feature_do_not_trigger_a_notice(env: StudioEnv) -> None:
    """旧 turn 的 `usage` 没有 `profile_name`：不知道上一轮用的什么，不发 notice。"""
    h = _make_harness(env)
    session = h.session()
    turn = await h.run(session, [fake.say("a")])
    with session_scope(env.engine) as db:
        db.execute(update(Turn).where(Turn.id == turn.id).values(usage={"steps": 0}))
    _switch(h, session, _add_profile(env, "fake-b"))

    await h.run(session, [fake.say("b")])

    assert _notices(h, session) == []


async def test_a_failed_turn_still_counts_as_the_last_run(env: StudioEnv) -> None:
    h = _make_harness(env)
    session = h.session()
    failed = await h.run(session, [fake.fail("boom")])
    assert failed.status == "failed"
    _switch(h, session, _add_profile(env, "fake-b"))

    await h.run(session, [fake.say("b")])

    assert [(n["from"], n["to"]) for n in _notices(h, session)] == [("fake", "fake-b")]


async def test_a_running_turn_already_records_its_profile(env: StudioEnv) -> None:
    """中断（重启恢复）不写 usage，所以开跑时就要记下用的配置，下一轮才知道上一轮用了谁。"""
    h = _make_harness(env)
    session = h.session()
    h.scripts.append([fake.sleep(5)])
    turn_id = await h.runner.start_turn(session, UserInput(text="x"))
    await _until(lambda: (get_turn(env.engine, turn_id) or _never()).status == "running")

    running = get_turn(env.engine, turn_id)

    assert running is not None and running.usage is not None
    assert (running.usage["profile_name"], running.usage["model"]) == ("fake", "fake")
    await h.runner.shutdown()


async def test_an_interrupted_turn_after_a_switch_still_counts_as_the_last_run(
    env: StudioEnv,
) -> None:
    h = _make_harness(env)
    session = h.session()
    await h.run(session, [fake.say("a")])
    _switch(h, session, _add_profile(env, "fake-b"))
    second = create_turn_if_session_idle(env.engine, session, "b")
    assert second is not None
    mark_turn_running(env.engine, second.id, start_snapshot_id=None)
    record_run_profile(env.engine, second.id, profile_name="fake-b", model="fake-b-model")
    h.runner.recover_on_startup()  # 崩溃/重启：turn 变 interrupted，不写 usage
    interrupted = get_turn(env.engine, second.id)
    assert interrupted is not None and interrupted.status == "interrupted"

    await h.run(session, [fake.say("c")])

    assert _notices(h, session) == []


def test_previous_run_lookup_finds_the_latest_recorded_profile(env: StudioEnv) -> None:
    """`before_turn_id` 之前最近一个记录了配置名的 turn。"""
    h = _make_harness(env)
    session = h.session()
    turns = []
    for i in range(3):
        turn = create_turn_if_session_idle(env.engine, session, str(i))
        assert turn is not None
        record_run_profile(env.engine, turn.id, profile_name=f"p{i}", model="m")
        finish_turn(
            env.engine,
            turn.id,
            status="done",
            end_snapshot_id=None,
            usage={"profile_name": f"p{i}", "model": "m"},
            cost_usd=None,
            error=None,
            resume_ref=None,
        )
        turns.append(turn)

    assert previous_run_profile_name(env.engine, session, turns[2].id) == "p1"
    assert previous_run_profile_name(env.engine, session, turns[0].id) is None


async def test_switch_notice_is_also_emitted_for_workspaceless_brainstorm_sessions(
    env: StudioEnv,
) -> None:
    env.registry.register(BRAINSTORM)
    h = _make_harness(env)
    profile = get_model_profile(env.engine, "fake")
    assert profile is not None
    session = create_session(
        env.engine,
        project_id=None,
        stage="brainstorm",
        model_profile_id=profile.id,
        runtime="fake",
    ).id
    await h.run(session, [fake.say("a")])

    _switch(h, session, _add_profile(env, "fake-b"))
    await h.run(session, [fake.say("b")])

    assert [(n["from"], n["to"]) for n in _notices(h, session)] == [("fake", "fake-b")]


class TestSetSessionModelIfIdle:
    async def test_refuses_while_a_turn_is_queued_or_running(self, env: StudioEnv) -> None:
        h = _make_harness(env)
        session = h.session()
        other = _add_profile(env, "fake-b")
        h.scripts.append(lambda: FakeRuntime([sleep(30)]))
        from studio.agent.runtime import UserInput

        turn_id = await h.runner.start_turn(session, UserInput(text="占位"))
        try:
            assert set_session_model_if_idle(env.engine, session, other) is None
        finally:
            h.runner.cancel(turn_id)
            await h.runner.wait(turn_id)

        result = set_session_model_if_idle(env.engine, session, other)
        assert result is not None and result.model_profile_id == other

    def test_unknown_session(self, env: StudioEnv) -> None:
        with pytest.raises(LookupError):
            set_session_model_if_idle(env.engine, "nope", "x")
