"""`suggestion` 事件（计划 M5 T9）：业务工具 `suggest_upstream_change` 成功后，TurnRunner 把新建的
回退建议作为持久事件推给会话（落库、可回放、走总线），并让工具拿到 `turn_id` 和直接上游。"""

from __future__ import annotations

from studio.agent import fake
from studio.db.repo.suggestions import list_suggestions
from studio.db.repo.turns import list_events

from .conftest import StudioEnv
from .test_runner import _collect, _drain, _make_harness


def _suggestion_events(env: StudioEnv, session_id: str) -> list:
    return [e for e in list_events(env.engine, session_id) if e.type == "suggestion"]


async def test_a_successful_suggestion_becomes_a_persisted_event_of_the_same_turn(
    env: StudioEnv,
) -> None:
    h = _make_harness(env)
    session = h.session(stage="animation")

    turn = await h.run(
        session,
        [
            fake.call_tool(
                "suggest_upstream_change", {"to_stage": "narrative", "content": "s-hook 旁白太长"}
            )
        ],
    )

    [row] = list_suggestions(env.engine, env.project_id)
    assert row.turn_id == turn.id
    [event] = _suggestion_events(env, session)
    assert event.turn_id == turn.id
    assert event.payload["suggestion_id"] == row.id
    assert event.payload["from_stage"] == "animation"
    assert event.payload["to_stage"] == "narrative"
    assert event.payload["content"] == "s-hook 旁白太长"
    assert event.payload["status"] == "open"


async def test_the_event_comes_after_the_tool_result_and_is_published_live(
    env: StudioEnv,
) -> None:
    h = _make_harness(env)
    session = h.session(stage="animation")
    received, pump = _collect(h.bus, session)

    await h.run(
        session,
        [fake.call_tool("suggest_upstream_change", {"to_stage": "narrative", "content": "x"})],
    )
    await _drain(pump)

    types = [e.type for e in received if e.type in ("tool_result", "suggestion")]
    assert types == ["tool_result", "suggestion"]


async def test_each_suggestion_in_a_turn_gets_exactly_one_event(env: StudioEnv) -> None:
    h = _make_harness(env)
    session = h.session(stage="animation")

    await h.run(
        session,
        [
            fake.call_tool("suggest_upstream_change", {"to_stage": "narrative", "content": "一"}),
            fake.call_tool("suggest_upstream_change", {"to_stage": "narrative", "content": "二"}),
        ],
    )

    events = _suggestion_events(env, session)
    assert [e.payload["content"] for e in events] == ["一", "二"]
    assert len({e.payload["suggestion_id"] for e in events}) == 2


async def test_a_rejected_call_creates_neither_a_row_nor_an_event(env: StudioEnv) -> None:
    h = _make_harness(env)
    session = h.session(stage="animation")

    await h.run(
        session,
        [fake.call_tool("suggest_upstream_change", {"to_stage": "topic", "content": "跳级了"})],
    )

    assert list_suggestions(env.engine, env.project_id) == []
    assert _suggestion_events(env, session) == []


async def test_the_tool_sees_the_direct_upstream_of_the_running_stage(env: StudioEnv) -> None:
    h = _make_harness(env)

    await h.run(h.session(stage="animation"), [fake.say("x")])
    assert h.contexts[-1].tool_context().upstream_stages == ("narrative",)
    await h.run(h.session(stage="narrative"), [fake.say("x")])
    assert h.contexts[-1].tool_context().upstream_stages == ("topic",)
    await h.run(h.session(stage="topic"), [fake.say("x")])
    assert h.contexts[-1].tool_context().upstream_stages == ()


async def test_the_tool_sees_the_running_turn_id(env: StudioEnv) -> None:
    h = _make_harness(env)
    session = h.session(stage="animation")

    turn = await h.run(session, [fake.say("x")])

    assert h.contexts[-1].tool_context().turn_id == turn.id
