"""会话内换模型（计划 M5 T7，决策 D3）：TurnRunner 每轮按会话**当前**的配置运行；
换了之后的第一轮向会话推一条 `notice`；`turns.usage` 记录每一轮实际用的模型。
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import update

from studio.agent import fake
from studio.agent.fake import FakeRuntime, sleep
from studio.db.engine import session_scope
from studio.db.models import ModelProfile, Turn
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session, set_session_model_if_idle
from studio.db.repo.turns import list_events
from studio.stages.brainstorm import STAGE as BRAINSTORM

from .conftest import StudioEnv
from .test_runner import Harness, _make_harness

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
