"""短片与"讲解 + 背景乐"的整条流水线（3A T9）：真实 `TurnRunner` + `FakeRuntime`。

每个阶段一轮：agent 写产物并调用阶段工具，之后定稿，下游的 `upstream/` 与时间轴随之变化。
非 `slow` 版用假浏览器池与恒等的脚本包装；`slow` 版用真实 Chromium 和真实 Seatbelt 沙箱，并检查
"`events.json` → 时间轴 → `env`"整条路径。
"""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from fixtures.html_engine.fakes import Behaviour, ScriptedBrowser
from fixtures.html_engine.fakes import digest as _digest
from fixtures.html_engine.worker_fakes import FakeBackend
from fixtures.synth_music import seed
from studio.agent.fake import FakeRuntime, call_tool, write
from studio.agent.runtime import UserInput
from studio.agent.stage_flow import finalize
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.snapshots import latest_snapshot
from studio.db.repo.stages import list_stages
from studio.db.repo.turns import get_turn, list_events
from studio.engines.render.html.pool import BrowserPool, set_browser_pool
from studio.stages.music import tool as music_tool
from studio.worker import run_once

from .conftest import ApiEnv

REF = Path(__file__).resolve().parents[1] / "fixtures" / "synth_music" / "compose_ref.py"


def _identity(workdir: Path):
    def wrap(argv: list[str], env: dict[str, str]) -> list[str]:
        return argv

    return wrap


@pytest.fixture
def plain_scripts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the synthesis script without the sandbox (the real one is covered by the slow tests)."""
    monkeypatch.setattr(music_tool, "sandbox_wrapper", _identity)


@pytest.fixture
async def fake_pool() -> AsyncIterator[Behaviour]:
    behaviour = Behaviour()
    # Frames follow both the narration beats (explainer) and the grid (reel, bed).
    behaviour.hash_fn = lambda t, tl: _digest(
        t,
        (tl.get("grid") or {}).get("beats", [])[:2],
        [b["start"] for n in tl["narration"] for b in n["beats"]],
    )

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


async def _turn(
    api_env: ApiEnv, pid: str, stage: str, script: list[Any], text: str = "继续"
) -> list[Any]:
    engine = api_env.app.state.engine
    profile = get_model_profile(engine, "fake")
    assert profile is not None
    session = create_session(
        engine, project_id=pid, stage=stage, model_profile_id=profile.id, runtime="fake"
    )
    api_env.app.state.runtime_factory.register("fake", lambda: FakeRuntime(script))
    runner = api_env.app.state.turn_runner
    turn_id = await runner.start_turn(session.id, UserInput(text=text))
    await runner.wait(turn_id)
    turn = get_turn(engine, turn_id)
    assert turn is not None and turn.status == "done", turn.error if turn else None
    return list_events(engine, session.id)


def _results(events: list[Any]) -> dict[str, list[dict[str, Any]]]:
    names = {e.payload["call_id"]: e.payload["name"] for e in events if e.type == "tool_call"}
    out: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        if e.type == "tool_result":
            out.setdefault(names[e.payload["call_id"]], []).append(e.payload)
    return out


def _finalize(api_env: ApiEnv, pid: str, stage: str) -> None:
    registry = api_env.app.state.registry
    assert registry.get(stage).finalize_blockers(api_env.workdir(pid)) == []
    finalize(api_env.app.state.engine, api_env.app.state.blobs, registry, pid, stage)


def _status(api_env: ApiEnv, pid: str) -> dict[str, str]:
    return {s.stage: s.status for s in list_stages(api_env.app.state.engine, pid)}


async def _run_reel_up_to_music(api_env: ApiEnv) -> str:
    engine, blobs = api_env.app.state.engine, api_env.app.state.blobs
    pid = seed.seed_reel_project(engine, blobs, data_dir=api_env.data_dir)

    events = await _turn(
        api_env, pid, "concept", [write("concept/brief.md", seed.BRIEF), call_tool("check_concept")]
    )
    check = _results(events)["check_concept"][0]
    assert check["is_error"] is False, check["text"]
    _finalize(api_env, pid, "concept")

    events = await _turn(
        api_env,
        pid,
        "beatsheet",
        [write("beatsheet/beatsheet.json", seed.BEATSHEET), call_tool("validate_beatsheet")],
    )
    sheet = _results(events)["validate_beatsheet"][0]
    assert sheet["is_error"] is False and "11.25" in sheet["text"], sheet["text"]
    _finalize(api_env, pid, "beatsheet")

    events = await _turn(
        api_env,
        pid,
        "music",
        [write("music/compose.py", REF.read_text()), call_tool("render_music")],
    )
    render = _results(events)["render_music"][0]
    assert render["is_error"] is False, render["text"]
    assert "配乐渲染成功" in render["text"] and "重定时校验通过" in render["text"]
    assert len(render["images"]) == 1
    _finalize(api_env, pid, "music")
    return pid


async def _animation_turn(api_env: ApiEnv, pid: str) -> dict[str, list[dict[str, Any]]]:
    events = await _turn(
        api_env,
        pid,
        "animation_html",
        [
            write("animation/scenes/s1.js", seed.REEL_SCENE),
            write("animation/scenes/s2.js", seed.REEL_SCENE),
            call_tool("validate_scenes_html"),
            call_tool("render_preview_html", {"scene_id": "s2"}),
        ],
    )
    return _results(events)


async def _check_reel(api_env: ApiEnv, pid: str) -> None:
    results = await _animation_turn(api_env, pid)
    validate = results["validate_scenes_html"][0]
    assert validate["is_error"] is False, validate["text"]
    assert validate["text"].splitlines()[0] == "全部 2 个镜头校验通过。"
    preview = results["render_preview_html"][0]
    assert preview["is_error"] is False, preview["text"]
    assert "镜头 s2 预览：时长 5.6" in preview["text"] and len(preview["images"]) == 1

    snapshot = latest_snapshot(api_env.app.state.engine, pid)
    assert snapshot is not None
    manifest = snapshot.manifest
    assert {
        "concept/brief.md",
        "beatsheet/beatsheet.json",
        "music/compose.py",
        "music/music.wav",
        "music/events.json",
        "music/analysis.json",
        "music/analysis.png",
        "music/render.json",
        "animation/scenes/s1.js",
    } <= set(manifest)
    assert not any(path.startswith("upstream/") for path in manifest)


async def test_motion_reel_pipeline_with_fakes(
    api_env: ApiEnv, plain_scripts: None, fake_pool: Behaviour
) -> None:
    pid = await _run_reel_up_to_music(api_env)
    assert _status(api_env, pid) == {
        "concept": "finalized",
        "beatsheet": "finalized",
        "music": "finalized",
        "animation_html": "active",
    }
    await _check_reel(api_env, pid)


async def test_changing_the_beatsheet_makes_the_music_stale_and_blocks_its_finalise(
    api_env: ApiEnv, plain_scripts: None, fake_pool: Behaviour
) -> None:
    pid = await _run_reel_up_to_music(api_env)
    longer = seed.BEATSHEET.replace('"bars": 3, "intent": "蓄力"', '"bars": 4, "intent": "蓄力"')
    assert longer != seed.BEATSHEET
    await _turn(api_env, pid, "beatsheet", [write("beatsheet/beatsheet.json", longer)])
    _finalize(api_env, pid, "beatsheet")
    assert _status(api_env, pid)["music"] == "stale"

    # The next music turn refreshes `upstream/`; the old render no longer matches the new grid.
    await _turn(api_env, pid, "music", [])
    blockers = api_env.app.state.registry.get("music").finalize_blockers(api_env.workdir(pid))
    assert any("上次渲染之后变了" in b for b in blockers), blockers


async def test_explainer_with_a_background_bed_pipeline_with_fakes(
    api_env: ApiEnv, plain_scripts: None, fake_pool: Behaviour
) -> None:
    engine, blobs = api_env.app.state.engine, api_env.app.state.blobs
    pid = seed.seed_bed_project(engine, blobs, data_dir=api_env.data_dir)
    assert _status(api_env, pid)["music"] == "active"

    events = await _turn(
        api_env,
        pid,
        "music",
        [write("music/compose.py", REF.read_text()), call_tool("render_music")],
    )
    render = _results(events)["render_music"][0]
    assert render["is_error"] is False, render["text"]
    _finalize(api_env, pid, "music")

    events_doc = json.loads((api_env.workdir(pid) / "music" / "events.json").read_text())
    assert events_doc["bpm"] == 100.0 and events_doc["offset"] == 0.1

    events = await _turn(
        api_env,
        pid,
        "animation_html",
        [
            write("animation/scenes/s-hook.js", _bed_scene()),
            write("animation/scenes/s-explain.js", _bed_scene()),
            call_tool("validate_scenes_html"),
        ],
    )
    validate = _results(events)["validate_scenes_html"][0]
    assert validate["is_error"] is False, validate["text"]


def _bed_scene() -> str:
    return (
        "module.exports = { draw(ctx, lt, env) {\n"
        "  ctx.fillStyle = '#102030'; ctx.fillRect(0, 0, env.W, env.H);\n"
        "  ctx.fillStyle = '#fff';\n"
        "  ctx.fillRect(100, 100 + 40 * env.cue(0), 200 + 100 * env.hit('kick'), 120);\n"
        "} };\n"
    )


# ---- 联调：真实沙箱与 Chromium ---------------------------------------------------------


@pytest.mark.slow
async def test_motion_reel_pipeline_with_the_real_sandbox_and_chromium(
    api_env: ApiEnv, real_pool: None
) -> None:
    pid = await _run_reel_up_to_music(api_env)
    await _check_reel(api_env, pid)


@pytest.mark.slow
async def test_events_json_reaches_the_scenes_through_the_timeline(
    api_env: ApiEnv, real_pool: None, tmp_path: Path
) -> None:
    """`events.json` → 时间轴 → `env.hit`：每个 kick 的起点上，包络恰好为 1。"""
    from studio.engines.render.html.assemble import assemble
    from studio.engines.render.html.browser import HtmlBrowser
    from studio.timeline.load import TimelineSources, load_timeline

    pid = await _run_reel_up_to_music(api_env)
    workdir = api_env.workdir(pid)
    loaded = load_timeline(TimelineSources(workdir, narration=False, music_source="synth"))
    timeline = loaded.timeline.model_dump(mode="json")
    kicks = [
        e
        for e in json.loads((workdir / "music" / "events.json").read_text())["events"]
        if e["name"] == "kick"
    ]
    assert len(kicks) >= 16
    assert [e["start"] for e in timeline["music"]["events"] if e["name"] == "kick"] == [
        e["start"] for e in kicks
    ]

    probe_dir = tmp_path / "probe"
    scenes = probe_dir / "animation" / "scenes"
    scenes.mkdir(parents=True)
    probe = (
        "window.__hits = window.__hits || {};\n"
        "module.exports = { draw(ctx, lt, env) {\n"
        "  window.__hits[env.t.toFixed(4)] = [env.hit('kick'), env.energy()];\n"
        "  ctx.fillRect(0, 0, 10, 10);\n"
        "} };\n"
    )
    for section in timeline["sections"]:
        (scenes / f"{section['id']}.js").write_text(probe)
    analysis = json.loads((workdir / "music" / "analysis.json").read_text())
    async with HtmlBrowser(ready_timeout=15, render_timeout=5) as browser:
        page = await browser.open_page(assemble(probe_dir, timeline))
        for kick in kicks[:12]:
            await page.render_hash(kick["start"] + 1e-4)
        hits: Mapping[str, list[float]] = await page.evaluate("window.__hits")
        await page.close()
    for kick in kicks[:12]:
        value, energy = hits[f"{kick['start'] + 1e-4:.4f}"]
        assert value == pytest.approx(1.0, abs=0.01)
        index = min(len(analysis["energy"]) - 1, int(kick["start"] / analysis["hop"]))
        assert 0.0 <= energy <= 1.0 and energy == pytest.approx(analysis["energy"][index], abs=0.15)
    shutil.rmtree(probe_dir, ignore_errors=True)


# ---- 成片（3B）：创建渲染任务 → worker → 定稿 --------------------------------------------


async def _bed_through_animation(api_env: ApiEnv) -> str:
    engine, blobs = api_env.app.state.engine, api_env.app.state.blobs
    pid = seed.seed_bed_project(engine, blobs, data_dir=api_env.data_dir)
    await _turn(
        api_env,
        pid,
        "music",
        [write("music/compose.py", REF.read_text()), call_tool("render_music")],
    )
    _finalize(api_env, pid, "music")
    await _turn(
        api_env,
        pid,
        "animation_html",
        [
            write("animation/scenes/s-hook.js", _bed_scene()),
            write("animation/scenes/s-explain.js", _bed_scene()),
            call_tool("validate_scenes_html"),
        ],
    )
    return pid


async def _render_final(api_env: ApiEnv, pid: str, backend: FakeBackend | None = None) -> Path:
    created = await api_env.client.post(f"/api/projects/{pid}/render")
    assert created.status_code == 201, created.text
    html_backend = backend.as_backend() if backend is not None else None
    engine, blobs = api_env.app.state.engine, api_env.app.state.blobs
    assert (
        await run_once(engine, blobs, data_dir=api_env.data_dir, html_backend=html_backend) is True
    )
    job = (await api_env.client.get(f"/api/projects/{pid}/jobs/{created.json()['id']}")).json()
    assert job["status"] == "done", job["error"]
    return api_env.workdir(pid) / "output" / "final.mp4"


async def test_a_reel_goes_from_the_score_to_a_finalised_render_with_fakes(
    api_env: ApiEnv, plain_scripts: None, fake_pool: Behaviour
) -> None:
    pid = await _run_reel_up_to_music(api_env)
    await _animation_turn(api_env, pid)
    backend = FakeBackend()
    final = await _render_final(api_env, pid, backend)
    assert final.is_file()
    [call] = backend.mix_calls
    assert call["tracks"] == [] and call["music"].duck_under_narration is False

    done = await api_env.client.post(f"/api/projects/{pid}/animation/finalize-render")
    assert done.status_code == 200, done.text
    assert _status(api_env, pid)["animation_html"] == "finalized"


async def test_an_explainer_bed_goes_to_a_finalised_render_with_fakes(
    api_env: ApiEnv, plain_scripts: None, fake_pool: Behaviour
) -> None:
    pid = await _bed_through_animation(api_env)
    backend = FakeBackend()
    await _render_final(api_env, pid, backend)
    [call] = backend.mix_calls
    assert len(call["tracks"]) == 2 and call["music"].duck_under_narration is True
    done = await api_env.client.post(f"/api/projects/{pid}/animation/finalize-render")
    assert done.status_code == 200, done.text


async def test_a_score_made_stale_after_the_scenes_blocks_the_render_with_the_reason(
    api_env: ApiEnv, plain_scripts: None, fake_pool: Behaviour
) -> None:
    pid = await _run_reel_up_to_music(api_env)
    await _animation_turn(api_env, pid)
    path = api_env.workdir(pid) / "beatsheet" / "beatsheet.json"
    path.write_text(path.read_text().replace("BUILD", "RISE", 1), encoding="utf-8")
    created = await api_env.client.post(f"/api/projects/{pid}/render")
    backend = FakeBackend()
    await run_once(
        api_env.app.state.engine,
        api_env.app.state.blobs,
        data_dir=api_env.data_dir,
        html_backend=backend.as_backend(),
    )
    job = (await api_env.client.get(f"/api/projects/{pid}/jobs/{created.json()['id']}")).json()
    assert job["status"] == "failed" and "配乐与当前时间轴不一致" in job["error"]
    assert backend.video_calls == []


def _audio_streams(path: Path) -> tuple[list[dict[str, Any]], float]:
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    info = json.loads(out)
    audio = [st for st in info["streams"] if st["codec_type"] == "audio"]
    return audio, float(info["format"]["duration"])


@pytest.mark.slow
async def test_a_reel_final_has_the_score_as_its_only_audio_with_real_ffmpeg(
    api_env: ApiEnv, real_pool: None
) -> None:
    pid = await _run_reel_up_to_music(api_env)
    await _animation_turn(api_env, pid)
    final = await _render_final(api_env, pid)
    audio, duration = _audio_streams(final)
    assert [a["codec_name"] for a in audio] == ["aac"]
    assert abs(duration - 11.25) <= 0.1
    meta = json.loads((api_env.workdir(pid) / "output" / "final.json").read_text())
    assert meta["audio_sources"] == {} and len(meta["music_hash"]) == 64


@pytest.mark.slow
async def test_an_explainer_bed_final_has_one_audio_track_with_real_ffmpeg(
    api_env: ApiEnv, real_pool: None
) -> None:
    pid = await _bed_through_animation(api_env)
    final = await _render_final(api_env, pid)
    audio, duration = _audio_streams(final)
    assert len(audio) == 1 and abs(duration - 3.0) <= 0.15
    meta = json.loads((api_env.workdir(pid) / "output" / "final.json").read_text())
    assert set(meta["audio_sources"]) == {"s-hook", "s-explain"} and meta["music_hash"]
