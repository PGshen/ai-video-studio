"""`explainer_html` 的动画阶段一轮（2A T8）：真实 `TurnRunner` + `FakeRuntime`。

叙事定稿（fixture）→ 阶段 `prepare_turn` 生成时间轴 → agent 写镜头、调用 `validate_scenes_html`
与 `render_preview_html`。非 `slow` 版注入假浏览器池；`slow` 版用真实 Chromium。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from fixtures.animation_html.seed import seed_animation_html_project
from fixtures.html_engine import projects as fx
from fixtures.html_engine.fakes import Behaviour, ScriptedBrowser
from studio.agent.fake import FakeRuntime, call_tool, write
from studio.agent.runtime import UserInput
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.snapshots import latest_snapshot
from studio.db.repo.turns import get_turn, list_events
from studio.engines.render.html.pool import BrowserPool, set_browser_pool

from .conftest import ApiEnv


@pytest.fixture
async def fake_pool() -> AsyncIterator[Behaviour]:
    behaviour = Behaviour()

    async def launcher() -> ScriptedBrowser:
        return ScriptedBrowser(behaviour)

    pool = BrowserPool(launcher=launcher)
    set_browser_pool(pool)
    yield behaviour
    set_browser_pool(None)
    await pool.close()


@pytest.fixture
async def real_pool() -> AsyncIterator[None]:
    pool = BrowserPool()
    set_browser_pool(pool)
    yield
    set_browser_pool(None)
    await pool.close()


async def _run_turn(api_env: ApiEnv) -> tuple[str, list[Any]]:
    engine = api_env.app.state.engine
    pid = seed_animation_html_project(engine, api_env.app.state.blobs, data_dir=api_env.data_dir)
    profile = get_model_profile(engine, "fake")
    assert profile is not None
    session = create_session(
        engine,
        project_id=pid,
        stage="animation_html",
        model_profile_id=profile.id,
        runtime="fake",
    )
    script = [
        write("animation/scenes/s-hook.js", fx.CUE_SCENE),
        write("animation/scenes/s-explain.js", fx.CUE_SCENE),
        call_tool("validate_scenes_html"),
        call_tool("render_preview_html", {"scene_id": "s-explain"}),
        write("animation/scenes/s-hook.js", fx.LITERAL_SCENE),
        call_tool("validate_scenes_html", {"scene_id": "s-hook"}),
    ]
    api_env.app.state.runtime_factory.register("fake", lambda: FakeRuntime(script))
    runner = api_env.app.state.turn_runner
    turn_id = await runner.start_turn(session.id, UserInput(text="写两个镜头并自检"))
    await runner.wait(turn_id)
    turn = get_turn(engine, turn_id)
    assert turn is not None and turn.status == "done", turn.error if turn else None
    events = list_events(engine, session.id)
    return pid, events


def _results(events: list[Any]) -> list[tuple[str, dict[str, Any]]]:
    names = {e.payload["call_id"]: e.payload["name"] for e in events if e.type == "tool_call"}
    return [(names[e.payload["call_id"]], e.payload) for e in events if e.type == "tool_result"]


async def _check(api_env: ApiEnv, pid: str, events: list[Any]) -> None:
    results = [(n, p) for n, p in _results(events) if n.endswith("_html")]
    assert [n for n, _ in results] == [
        "validate_scenes_html",
        "render_preview_html",
        "validate_scenes_html",
    ]
    validate, preview, literal = (p for _, p in results)
    assert validate["is_error"] is False, validate["text"]
    assert validate["text"].splitlines()[0] == "全部 2 个镜头校验通过。"
    assert preview["is_error"] is False, preview["text"]
    assert len(preview["images"]) == 1
    assert literal["is_error"] is True
    assert "镜头 s-hook：" in literal["text"] and "env.cue" in literal["text"]

    # `upstream/` 每轮结束会重建，派生的时间轴和金样本只在轮内存在；工具通过说明它们当时可用。
    assert "镜头 s-explain 预览：时长 1.60s" in preview["text"]

    snapshot = latest_snapshot(api_env.app.state.engine, pid)
    assert snapshot is not None
    manifest = snapshot.manifest
    assert {"animation/scenes/s-hook.js", "animation/scenes/s-explain.js"} <= set(manifest)
    assert not any(path.startswith("upstream/") for path in manifest)


async def test_turn_with_fake_pool(api_env: ApiEnv, fake_pool: Behaviour) -> None:
    pid, events = await _run_turn(api_env)
    await _check(api_env, pid, events)


@pytest.mark.slow
async def test_turn_with_real_chromium(api_env: ApiEnv, real_pool: None) -> None:
    pid, events = await _run_turn(api_env)
    await _check(api_env, pid, events)
