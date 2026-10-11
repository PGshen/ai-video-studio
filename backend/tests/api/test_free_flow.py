"""自由项目从创建到成片定稿（free-mode 计划 T7）：真实 `TurnRunner` + `FakeRuntime`。

每种形态一个对话阶段：agent 在一轮里写产物并调用工具；随后 `POST /render`，worker 用假后端出片，
`finalize-render` 定稿、项目完成。假浏览器池、假 TTS、不经沙箱的合成脚本，不起 Chromium 与 ffmpeg。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from fixtures.html_engine import projects as fx
from fixtures.html_engine.fakes import Behaviour, ScriptedBrowser
from fixtures.html_engine.fakes import digest as _digest
from fixtures.html_engine.worker_fakes import FakeBackend
from fixtures.import_music import write_click_song
from fixtures.synth_music import seed
from studio.agent.fake import FakeRuntime, call_tool, shell_write, write
from studio.agent.runtime import UserInput
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.snapshots import latest_snapshot
from studio.db.repo.turns import get_turn, list_events
from studio.engines.render.html.pool import BrowserPool, set_browser_pool
from studio.stages.common.narration import synthesize_tts as synthesize_tts_module
from studio.stages.common.score import tool as music_tool
from studio.worker import run_once

from .conftest import ApiEnv
from .test_narrative_flow import _NARRATIVE_DOC, _CharTimestampTTSEngine

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synth_music"
REF = FIXTURES / "compose_ref.py"
FREE = FIXTURES / "compose_free.py"

_CUE_SCENE = fx.CUE_SCENE
_BED_SCENE = (
    "module.exports = { draw(ctx, lt, env) {\n"
    "  ctx.fillStyle = '#102030'; ctx.fillRect(0, 0, env.W, env.H);\n"
    "  ctx.fillStyle = '#fff';\n"
    "  ctx.fillRect(100, 100 + 40 * env.cue(0), 200 + 100 * env.hit('kick'), 120);\n"
    "} };\n"
)
_MV_SCENE = (
    "module.exports = { draw(ctx, lt, env) {\n"
    "  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, env.W, env.H);\n"
    "  ctx.fillStyle = '#fff'; ctx.fillRect(100, 100, 200 + 200 * env.hit('beat'), 120);\n"
    "} };\n"
)


def _identity(workdir: Path):
    def wrap(argv: list[str], env: dict[str, str]) -> list[str]:
        return argv

    return wrap


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(music_tool, "sandbox_wrapper", _identity)
    monkeypatch.setattr(
        synthesize_tts_module, "_ENGINE_FACTORY", lambda _voices: _CharTimestampTTSEngine()
    )


@pytest.fixture(autouse=True)
async def fake_pool() -> AsyncIterator[Behaviour]:
    behaviour = Behaviour()
    behaviour.hash_fn = lambda t, tl: _digest(
        t,
        [e["start"] for e in (tl.get("music") or {}).get("events", [])[:2]],
        [b["start"] for n in tl["narration"] for b in n["beats"]],
    )

    async def launcher() -> ScriptedBrowser:
        return ScriptedBrowser(behaviour)

    pool = BrowserPool(launcher=launcher)
    set_browser_pool(pool)
    yield behaviour
    set_browser_pool(None)
    await pool.close()


async def _create(api_env: ApiEnv, narration: bool, music_source: str) -> str:
    response = await api_env.client.post(
        "/api/projects",
        json={
            "title": "自由",
            "mode": "free",
            "engine": "html",
            "narration": narration,
            "music_source": music_source,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _turn(
    api_env: ApiEnv, pid: str, stage: str, script: list[Any] | None
) -> dict[str, list[dict[str, Any]]]:
    engine = api_env.app.state.engine
    profile = get_model_profile(engine, "fake")
    assert profile is not None
    session = create_session(
        engine, project_id=pid, stage=stage, model_profile_id=profile.id, runtime="fake"
    )
    api_env.app.state.runtime_factory.register("fake", lambda: FakeRuntime(script))
    runner = api_env.app.state.turn_runner
    turn_id = await runner.start_turn(session.id, UserInput(text="按这个做"))
    await runner.wait(turn_id)
    turn = get_turn(engine, turn_id)
    assert turn is not None and turn.status == "done", turn.error if turn else None
    events = list_events(engine, session.id)
    names = {e.payload["call_id"]: e.payload["name"] for e in events if e.type == "tool_call"}
    results: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.type == "tool_result":
            results.setdefault(names[event.payload["call_id"]], []).append(event.payload)
    return results


def _assert_ok(results: dict[str, list[dict[str, Any]]], *names: str) -> None:
    for name in names:
        for result in results[name]:
            assert result["is_error"] is False, (name, result["text"])


async def _render_and_finalize(api_env: ApiEnv, pid: str, stage: str) -> FakeBackend:
    client = api_env.client
    created = await client.post(f"/api/projects/{pid}/render")
    assert created.status_code == 201, created.text
    backend = FakeBackend()
    engine, blobs = api_env.app.state.engine, api_env.app.state.blobs
    claimed = await run_once(
        engine, blobs, data_dir=api_env.data_dir, html_backend=backend.as_backend()
    )
    assert claimed is True
    job = (await client.get(f"/api/projects/{pid}/jobs/{created.json()['id']}")).json()
    assert job["status"] == "done", job["error"]

    finalized = await client.post(f"/api/projects/{pid}/animation/finalize-render")
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["stage"] == stage
    project = (await client.get(f"/api/projects/{pid}")).json()
    assert project["status"] == "completed"
    return backend


def _narration_steps() -> list[Any]:
    return [
        write("notes/outline.md", "# 大纲\n\n- 钩子\n- 分治\n"),
        write("narrative/narrative.json", json.dumps(_NARRATIVE_DOC, ensure_ascii=False)),
        call_tool("validate_narrative"),
        call_tool("synthesize_tts"),
    ]


async def test_free_explainer_from_creation_to_a_finalized_render(api_env: ApiEnv) -> None:
    pid = await _create(api_env, narration=True, music_source="none")

    results = await _turn(
        api_env,
        pid,
        "free_explainer",
        [
            *_narration_steps(),
            write("animation/scenes/s-hook.js", _CUE_SCENE),
            write("animation/scenes/s-explain.js", _CUE_SCENE),
            call_tool("validate_scenes_html"),
            call_tool("render_preview_html", {"scene_id": "s-hook"}),
        ],
    )
    _assert_ok(
        results,
        "validate_narrative",
        "synthesize_tts",
        "validate_scenes_html",
        "render_preview_html",
    )
    snapshot = latest_snapshot(api_env.app.state.engine, pid)
    assert snapshot is not None
    assert {
        "notes/project.md",
        "notes/outline.md",
        "narrative/narrative.json",
        "narrative/timing.json",
        "animation/scenes/s-hook.js",
    } <= set(snapshot.manifest)

    backend = await _render_and_finalize(api_env, pid, "free_explainer")
    assert len(backend.video_calls) == 1


async def test_free_explainer_with_background_music(api_env: ApiEnv) -> None:
    pid = await _create(api_env, narration=True, music_source="synth")

    results = await _turn(
        api_env,
        pid,
        "free_explainer",
        [
            *_narration_steps(),
            write("music/compose.py", REF.read_text()),
            call_tool("render_music"),
            write("animation/scenes/s-hook.js", _BED_SCENE),
            write("animation/scenes/s-explain.js", _BED_SCENE),
            call_tool("validate_scenes_html"),
        ],
    )
    _assert_ok(results, "synthesize_tts", "render_music", "validate_scenes_html")
    assert "重定时校验通过" in results["render_music"][0]["text"]

    backend = await _render_and_finalize(api_env, pid, "free_explainer")
    final = json.loads((api_env.workdir(pid) / "output" / "final.json").read_text())
    assert final["music_hash"]
    assert len(backend.mix_calls) == 1


async def test_free_reel_from_creation_to_a_finalized_render(api_env: ApiEnv) -> None:
    pid = await _create(api_env, narration=False, music_source="synth")

    results = await _turn(
        api_env,
        pid,
        "free_produce",
        [
            write("music/compose.py", FREE.read_text()),
            call_tool("render_music"),
            write("animation/shots.json", json.dumps(seed.SHOTS)),
            write("animation/scenes/s1.js", seed.REEL_SCENE),
            write("animation/scenes/s2.js", seed.REEL_SCENE),
            call_tool("validate_scenes_html"),
        ],
    )
    _assert_ok(results, "render_music", "validate_scenes_html")
    assert (
        api_env.app.state.registry.get("free_produce").finalize_blockers(api_env.workdir(pid)) == []
    )

    await _render_and_finalize(api_env, pid, "free_produce")


async def test_free_mv_uploads_a_song_in_the_single_stage(api_env: ApiEnv, tmp_path: Path) -> None:
    pid = await _create(api_env, narration=False, music_source="import")
    song = write_click_song(tmp_path / "song.wav")

    uploaded = await api_env.client.post(
        f"/api/projects/{pid}/music/source",
        files={"file": ("song.wav", song.read_bytes(), "application/octet-stream")},
    )
    assert uploaded.status_code == 200, uploaded.text

    shots = {
        "shots": [
            {"id": "intro", "label": "intro", "start": 0.0, "end": 8.0},
            {"id": "verse", "label": "verse", "start": 8.0, "end": 20.0},
        ]
    }
    results = await _turn(
        api_env,
        pid,
        "free_produce",
        [
            call_tool("analyze_music"),
            write("animation/shots.json", json.dumps(shots)),
            write("animation/scenes/intro.js", _MV_SCENE),
            write("animation/scenes/verse.js", _MV_SCENE),
            call_tool("validate_scenes_html"),
        ],
    )
    _assert_ok(results, "analyze_music", "validate_scenes_html")

    await _render_and_finalize(api_env, pid, "free_produce")


async def test_upload_is_refused_while_a_turn_is_running(api_env: ApiEnv, tmp_path: Path) -> None:
    pid = await _create(api_env, narration=False, music_source="import")
    song = write_click_song(tmp_path / "song.wav")
    turn_id = await api_env.make_busy(pid, stage="free_produce")

    response = await api_env.client.post(
        f"/api/projects/{pid}/music/source",
        files={"file": ("song.wav", song.read_bytes(), "application/octet-stream")},
    )

    assert response.status_code == 409
    await api_env.release_busy(turn_id)


async def test_style_edits_through_the_shell_are_restored(api_env: ApiEnv) -> None:
    pid = await _create(api_env, narration=False, music_source="synth")
    style = api_env.workdir(pid) / "style" / "STYLE.md"
    before = style.read_text(encoding="utf-8")

    await _turn(
        api_env,
        pid,
        "free_produce",
        [shell_write("style/STYLE.md", "hijacked\n"), write("notes/keep.md", "ok\n")],
    )

    assert style.read_text(encoding="utf-8") == before
    assert (api_env.workdir(pid) / "notes" / "keep.md").read_text(encoding="utf-8") == "ok\n"


async def test_the_default_fake_turn_writes_into_notes(api_env: ApiEnv) -> None:
    pid = await _create(api_env, narration=True, music_source="none")

    await _turn(api_env, pid, "free_explainer", None)

    assert (api_env.workdir(pid) / "notes" / "fake-note.md").is_file()


async def test_files_api_writes_notes_but_not_style(api_env: ApiEnv) -> None:
    pid = await _create(api_env, narration=True, music_source="none")
    base = f"/api/projects/{pid}/files"
    params = {"stage": "free_explainer"}

    ok = await api_env.client.put(f"{base}/notes/x.md", params=params, json={"content": "x\n"})
    refused = await api_env.client.put(
        f"{base}/style/STYLE.md", params=params, json={"content": "x\n"}
    )

    assert ok.status_code == 200, ok.text
    assert refused.status_code == 403
