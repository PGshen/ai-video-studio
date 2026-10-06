"""`validate_scenes_html` 与 `render_preview_html` 在 `produce` 阶段（produce-stage 设计 §7，T5）。

时间轴不来自 `upstream/timeline.json`，而是由工具即时从 `animation/shots.json`、`music/` 构建；
音乐平移检查只给警告；预览采样加入能量峰值。用假浏览器驱动，不需要 Chromium。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from fixtures.html_engine import projects as fx
from fixtures.html_engine.fakes import Behaviour, ScriptedBrowser
from fixtures.html_engine.fakes import digest as _digest
from studio.agent.tools import ToolContext, ToolResult, invoke_tool
from studio.engines.render.html.pool import BrowserPool, set_browser_pool
from studio.stages.common.scenes.render_preview_html import RENDER_PREVIEW_HTML_TOOL
from studio.stages.common.scenes.validate_scenes_html import VALIDATE_SCENES_HTML_TOOL

DURATION = 12.0
_SCENE = (
    "module.exports = { draw(ctx, lt, env) { ctx.fillRect(0, 0, 10 + env.hit('kick'), 10); } };\n"
)


@pytest.fixture
async def behaviour() -> AsyncIterator[Behaviour]:
    b = Behaviour()

    async def launcher() -> ScriptedBrowser:
        return ScriptedBrowser(b)

    pool = BrowserPool(launcher=launcher)
    set_browser_pool(pool)
    yield b
    set_browser_pool(None)
    await pool.close()


def _write(root: Path, relpath: str, data: Any) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _energy() -> list[float]:
    values = [0.1] * 121
    values[30] = 0.9  # a peak at 3.0 s, inside the first shot
    values[100] = 0.8  # a peak at 10.0 s, inside the second shot
    return values


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A produce workspace with no `upstream/` at all."""
    _write(
        tmp_path,
        "music/events.json",
        {
            "bpm": 120,
            "duration": DURATION,
            "events": [
                *(
                    {"name": "kick", "kind": "onset", "start": 0.5 * i, "end": 0.5 * i + 0.1}
                    for i in range(int(DURATION * 2))
                ),
                {"name": "impact", "kind": "onset", "start": 6.0, "end": 6.4},
                {"name": "riser", "kind": "sweep", "start": 4.0, "end": 6.0},
            ],
        },
    )
    _write(tmp_path, "music/analysis.json", {"hop": 0.1, "energy": _energy(), "duration": DURATION})
    _write(
        tmp_path,
        "animation/shots.json",
        {
            "shots": [
                {"id": "intro", "label": "开场", "start": 0, "end": 6},
                {"id": "drop", "label": "高潮", "start": 6, "end": DURATION},
            ]
        },
    )
    fx.write_project(
        tmp_path,
        scenes={"intro": _SCENE, "drop": _SCENE},
        global_js="module.exports = { post(ctx, t, env) {} };\n",
    )
    return tmp_path


def _ctx(workdir: Path) -> ToolContext:
    return ToolContext(
        project_id="p",
        stage="produce",
        workdir=workdir,
        record_tool_write=lambda relpath, sha256: None,
    )


async def _validate(workdir: Path, **args: Any) -> ToolResult:
    return await invoke_tool(VALIDATE_SCENES_HTML_TOOL, _ctx(workdir), args)


async def _preview(workdir: Path, **args: Any) -> ToolResult:
    return await invoke_tool(RENDER_PREVIEW_HTML_TOOL, _ctx(workdir), args)


def _follows_the_music(t: float, tl: Mapping[str, Any]) -> str:
    return _digest(t, tl["music"]["events"][0]["start"], tl["music"]["energy"]["values"][:5])


def test_both_tools_belong_to_the_produce_stage_too() -> None:
    assert VALIDATE_SCENES_HTML_TOOL.stages == {"animation_html", "produce"}
    assert RENDER_PREVIEW_HTML_TOOL.stages == {"animation_html", "produce"}


async def test_the_timeline_is_built_on_the_fly_from_shots_and_music(
    project: Path, behaviour: Behaviour
) -> None:
    behaviour.hash_fn = _follows_the_music
    result = await _validate(project)
    assert not result.is_error, result.text
    assert "全部 2 个镜头校验通过" in result.text
    assert not (project / "upstream").exists()


async def test_editing_the_shots_is_picked_up_immediately(
    project: Path, behaviour: Behaviour
) -> None:
    behaviour.hash_fn = _follows_the_music
    _write(
        project,
        "animation/shots.json",
        {"shots": [{"id": "intro", "start": 0, "end": 4}, {"id": "drop", "start": 4, "end": 12}]},
    )
    result = await _validate(project, scene_id="drop")
    assert not result.is_error, result.text
    page = behaviour.assembled[0]
    assert '"start": 4' in page.html or '"start":4' in page.html


@pytest.mark.parametrize("tool", ["validate", "preview"])
async def test_missing_shots_says_where_to_write_them(
    project: Path, behaviour: Behaviour, tool: str
) -> None:
    (project / "animation" / "shots.json").unlink()
    result = await (
        _validate(project) if tool == "validate" else _preview(project, scene_id="intro")
    )
    assert result.is_error
    assert "时间轴不可用" in result.text and "animation/shots.json" in result.text
    assert behaviour.opened == 0


async def test_shots_that_do_not_cover_the_music_name_both_lengths(
    project: Path, behaviour: Behaviour
) -> None:
    _write(project, "animation/shots.json", {"shots": [{"id": "intro", "start": 0, "end": 9}]})
    result = await _validate(project)
    assert result.is_error and "12" in result.text and "9" in result.text
    assert behaviour.opened == 0


async def test_missing_music_says_to_render_it(project: Path, behaviour: Behaviour) -> None:
    (project / "music" / "events.json").unlink()
    result = await _validate(project)
    assert result.is_error and "render_music" in result.text


async def test_a_shot_without_a_scene_file_is_reported_by_id(
    project: Path, behaviour: Behaviour
) -> None:
    (project / "animation" / "scenes" / "drop.js").unlink()
    result = await _validate(project)
    assert result.is_error and "镜头 drop：" in result.text and "镜头 intro：" not in result.text


async def test_unknown_scene_id_lists_the_shots(project: Path, behaviour: Behaviour) -> None:
    result = await _validate(project, scene_id="nope")
    assert result.is_error and "intro" in result.text and "drop" in result.text


async def test_a_scene_that_ignores_the_music_is_only_a_warning(
    project: Path, behaviour: Behaviour
) -> None:
    behaviour.hash_fn = lambda t, tl: _digest(t)
    result = await _validate(project, scene_id="intro")
    assert not result.is_error, result.text
    assert "警告 镜头 intro：" in result.text and "音乐平移 0.2 秒" in result.text
    assert "env.hit" in result.text and "env.bt" not in result.text


async def test_a_scene_that_ignores_most_of_the_music_is_a_warning_too(
    project: Path, behaviour: Behaviour
) -> None:
    def hash_fn(t: float, tl: Mapping[str, Any]) -> str:
        return _digest(t, tl["music"]["events"][0]["start"]) if t < 0.5 else _digest(t)

    behaviour.hash_fn = hash_fn
    result = await _validate(project, scene_id="intro")
    assert not result.is_error, result.text
    assert "警告 镜头 intro：" in result.text


async def test_the_shift_check_still_runs_without_the_global_script(
    project: Path, behaviour: Behaviour
) -> None:
    (project / "animation" / "global.js").unlink()
    behaviour.hash_fn = _follows_the_music
    result = await _validate(project)
    assert not result.is_error, result.text
    assert behaviour.opened == 1


async def test_the_beat_checks_are_not_applied(project: Path, behaviour: Behaviour) -> None:
    behaviour.hash_fn = _follows_the_music
    result = await _validate(project)
    assert "旁白 beat" not in result.text and "env.cue" not in result.text


async def test_a_literal_time_comparison_is_still_a_warning(
    project: Path, behaviour: Behaviour
) -> None:
    behaviour.hash_fn = _follows_the_music
    (project / "animation" / "scenes" / "intro.js").write_text(
        "module.exports = { draw(ctx, lt, env) { if (lt > 3.5) ctx.fillRect(0, 0, 1, 1); } };\n"
    )
    result = await _validate(project, scene_id="intro")
    assert not result.is_error
    assert "字面量" in result.text


async def test_too_many_shots_is_a_warning(project: Path, behaviour: Behaviour) -> None:
    behaviour.hash_fn = _follows_the_music
    count = 41
    length = DURATION / count
    shots = [
        {"id": f"s{i}", "start": round(i * length, 6), "end": round((i + 1) * length, 6)}
        for i in range(count)
    ]
    shots[-1]["end"] = DURATION
    _write(project, "animation/shots.json", {"shots": shots})
    fx.write_project(project, scenes={s["id"]: _SCENE for s in shots})
    result = await _validate(project, scene_id="s0")
    assert not result.is_error, result.text
    assert "41" in result.text and "40" in result.text


async def test_preview_samples_energy_peaks_and_the_rarest_events(
    project: Path, behaviour: Behaviour
) -> None:
    result = await _preview(project, scene_id="drop")
    assert not result.is_error, result.text
    seen = [
        float(line.split()[0][2:]) for line in result.text.splitlines() if line.startswith("t=")
    ]
    assert seen and all(6.0 <= t < DURATION for t in seen) and len(seen) <= 16
    assert any(abs(t - 6.04) < 0.01 for t in seen)  # the rarest onset: `impact`
    assert any(abs(t - 10.0) < 0.15 for t in seen)  # the energy peak in this shot
    assert len(result.images) == 1


async def test_preview_picture_stays_within_the_shared_budget(
    project: Path, behaviour: Behaviour
) -> None:
    import base64

    result = await _preview(project, scene_id="intro")
    assert len(base64.b64decode(result.images[0].data_base64)) <= 300_000


async def test_beat_and_downbeat_events_from_a_song_do_not_flood_the_samples(
    tmp_path: Path, behaviour: Behaviour
) -> None:
    beats = [round(0.5 * i, 3) for i in range(80)]
    _write(
        tmp_path,
        "music/analysis.json",
        {
            "source_hash": "abc",
            "duration": 40.0,
            "bpm": 120.0,
            "offset": 0.0,
            "hop": 0.5,
            "energy": [0.2] * 80,
            "beats": beats,
            "downbeats": beats[::4],
        },
    )
    (tmp_path / "music" / "source.mp3").write_bytes(b"x")
    _write(tmp_path, "animation/shots.json", {"shots": [{"id": "all", "start": 0, "end": 40}]})
    fx.write_project(tmp_path, scenes={"all": _SCENE})
    result = await _preview(tmp_path, scene_id="all")
    assert not result.is_error, result.text
    assert len([line for line in result.text.splitlines() if line.startswith("t=")]) == 16
