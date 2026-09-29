"""联网模式开关 `STUDIO_WEB_MODE`（决策 D1；计划 M4 T5）：TurnRunner 按模式决定
`TurnContext.allow_web`（原生联网）和工具列表里有没有自建联网工具。
"""

from __future__ import annotations

from typing import Literal

import pytest

from studio.agent import fake
from studio.agent.tools import WEB_TOOL_NAMES
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.stages.brainstorm import STAGE as BRAINSTORM

from .conftest import StudioEnv
from .test_runner import Harness, _make_harness


def _harness(env: StudioEnv, mode: Literal["tools", "native"]) -> Harness:
    env.registry.register(BRAINSTORM)
    return _make_harness(env, web_mode=mode)


def _brainstorm_session(h: Harness) -> str:
    profile = get_model_profile(h.env.engine, "fake")
    assert profile is not None
    return create_session(
        h.env.engine,
        project_id=None,
        stage="brainstorm",
        model_profile_id=profile.id,
        runtime="fake",
    ).id


def _tool_names(h: Harness) -> set[str]:
    return {t.name for t in h.contexts[-1].tools}


@pytest.mark.parametrize("stage", ["topic", "brainstorm"])
async def test_tools_mode_offers_self_built_tools_and_no_native_web(
    env: StudioEnv, stage: str
) -> None:
    h = _harness(env, "tools")
    session = _brainstorm_session(h) if stage == "brainstorm" else h.session(stage=stage)
    await h.run(session, [fake.say("x")])

    assert h.contexts[-1].allow_web is False
    assert WEB_TOOL_NAMES <= _tool_names(h)


@pytest.mark.parametrize("stage", ["topic", "brainstorm"])
async def test_native_mode_uses_native_web_and_hides_self_built_tools(
    env: StudioEnv, stage: str
) -> None:
    h = _harness(env, "native")
    session = _brainstorm_session(h) if stage == "brainstorm" else h.session(stage=stage)
    await h.run(session, [fake.say("x")])

    assert h.contexts[-1].allow_web is True
    assert not (WEB_TOOL_NAMES & _tool_names(h))


@pytest.mark.parametrize("mode", ["tools", "native"])
async def test_narrative_and_animation_never_get_web(
    env: StudioEnv, mode: Literal["tools", "native"]
) -> None:
    h = _harness(env, mode)
    for stage in ("narrative", "animation"):
        await h.run(h.session(stage=stage), [fake.say("x")])
        assert h.contexts[-1].allow_web is False
        assert not (WEB_TOOL_NAMES & _tool_names(h))


async def test_native_mode_keeps_the_stages_other_tools(env: StudioEnv) -> None:
    h = _harness(env, "native")
    await h.run(_brainstorm_session(h), [fake.say("x")])
    assert {"list_ideas", "create_idea", "update_idea"} <= _tool_names(h)
