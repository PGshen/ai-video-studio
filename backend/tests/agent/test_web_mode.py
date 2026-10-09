"""联网模式开关 `STUDIO_WEB_MODE`（决策 D1；计划 M4 T5）：TurnRunner 按模式决定
`TurnContext.allow_web`（原生联网）和工具列表里有没有自建联网工具。
"""

from __future__ import annotations

from typing import Literal

import pytest

from studio.agent import fake
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.settings import update_settings
from studio.stages.brainstorm import STAGE as BRAINSTORM

from .conftest import StudioEnv
from .test_runner import Harness, _make_harness

WEB_TOOLS = {"web_search", "fetch_url"}


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
    assert WEB_TOOLS <= _tool_names(h)


@pytest.mark.parametrize("stage", ["topic", "brainstorm"])
async def test_native_mode_uses_native_web_and_hides_self_built_tools(
    env: StudioEnv, stage: str
) -> None:
    h = _harness(env, "native")
    session = _brainstorm_session(h) if stage == "brainstorm" else h.session(stage=stage)
    await h.run(session, [fake.say("x")])

    assert h.contexts[-1].allow_web is True
    assert not (WEB_TOOLS & _tool_names(h))


@pytest.mark.parametrize("mode", ["tools", "native"])
async def test_narrative_and_animation_never_get_web(
    env: StudioEnv, mode: Literal["tools", "native"]
) -> None:
    h = _harness(env, mode)
    for stage in ("narrative", "animation_html"):
        await h.run(h.session(stage=stage), [fake.say("x")])
        assert h.contexts[-1].allow_web is False
        assert not (WEB_TOOLS & _tool_names(h))


async def test_native_mode_keeps_the_stages_other_tools(env: StudioEnv) -> None:
    h = _harness(env, "native")
    await h.run(_brainstorm_session(h), [fake.say("x")])
    assert {"list_ideas", "create_idea", "update_idea"} <= _tool_names(h)


async def test_native_mode_falls_back_to_self_built_tools_for_litellm_models(
    env: StudioEnv,
) -> None:
    """经 LiteLLM 的非官方 OpenAI 兼容模型没有原生联网：保留自建工具，不开 `allow_web`。"""
    from studio.db.engine import session_scope
    from studio.db.models import ModelProfile

    h = _harness(env, "native")
    with session_scope(env.engine) as db:
        row = ModelProfile(name="deepseek-like", provider="deepseek", model="m", runtime="openai")
        db.add(row)
        db.flush()
        profile_id = row.id
    session = create_session(
        env.engine,
        project_id=None,
        stage="brainstorm",
        model_profile_id=profile_id,
        runtime="fake",
    )
    await h.run(session.id, [fake.say("x")])

    assert h.contexts[-1].allow_web is False
    assert WEB_TOOLS <= _tool_names(h)


async def test_ui_override_wins_over_env_and_clearing_falls_back(env: StudioEnv) -> None:
    """界面设置的联网模式每轮重新读取：同一个 runner 里改了，下一轮工具列表就变（M5 T1）。"""
    h = _harness(env, "tools")
    session = _brainstorm_session(h)

    await h.run(session, [fake.say("x")])
    assert h.contexts[-1].allow_web is False
    assert WEB_TOOLS <= _tool_names(h)

    update_settings(env.engine, {"web_mode": "native"})
    await h.run(session, [fake.say("x")])
    assert h.contexts[-1].allow_web is True
    assert not (WEB_TOOLS & _tool_names(h))

    update_settings(env.engine, {"web_mode": None})
    await h.run(session, [fake.say("x")])
    assert h.contexts[-1].allow_web is False
    assert WEB_TOOLS <= _tool_names(h)


async def test_ui_tools_override_beats_native_env(env: StudioEnv) -> None:
    h = _harness(env, "native")
    update_settings(env.engine, {"web_mode": "tools"})

    await h.run(_brainstorm_session(h), [fake.say("x")])

    assert h.contexts[-1].allow_web is False
    assert WEB_TOOLS <= _tool_names(h)


def test_stage_flags() -> None:
    from studio.stages.animation_html import STAGE as ANIMATION
    from studio.stages.narrative import STAGE as NARRATIVE
    from studio.stages.topic import STAGE as TOPIC

    assert BRAINSTORM.workspaceless is True
    assert not any(s.workspaceless for s in (TOPIC, NARRATIVE, ANIMATION))
    for stage in (BRAINSTORM, TOPIC):
        assert {t.name for t in stage.tools() if t.web} == WEB_TOOLS
