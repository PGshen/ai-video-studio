"""`/api/projects/{id}/animation/html-preview/`（2B T5）：iframe 实时预览的页面、资源与 `meta`。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fixtures.animation.seed import seed_animation_project
from fixtures.animation_html.seed import seed_animation_html_project
from fixtures.html_engine import projects as fx

from .conftest import ApiEnv, assert_detail


@pytest.fixture
async def pid(api_env: ApiEnv) -> str:
    project_id = seed_animation_html_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    fx.write_project(
        api_env.workdir(project_id),
        scenes={"s-hook": fx.CUE_SCENE, "s-explain": fx.PURE_SCENE_PLAIN},
        lib={"colors": "const INK = '#fff';\n"},
    )
    return project_id


def _base(project_id: str) -> str:
    return f"/api/projects/{project_id}/animation/html-preview"


def _assert_preview_headers(response) -> None:
    assert response.headers["cache-control"] == "no-store"
    # No CORS: the canvas loads the self-contained page itself, so no other origin needs to read it.
    assert "access-control-allow-origin" not in response.headers


async def test_page_is_assembled_in_preview_mode_from_the_current_workspace(
    api_env: ApiEnv, pid: str
) -> None:
    response = await api_env.client.get(f"{_base(pid)}/")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    _assert_preview_headers(response)
    assert "window.__PREVIEW__" in response.text
    assert "window.__TIMELINE__" in response.text
    assert "s-hook" in response.text


async def test_page_is_also_served_without_the_trailing_slash(api_env: ApiEnv, pid: str) -> None:
    response = await api_env.client.get(_base(pid))
    assert response.status_code == 200
    assert "window.__PREVIEW__" in response.text


async def test_scripts_fonts_and_assets_referenced_by_the_page_can_be_fetched(
    api_env: ApiEnv, pid: str
) -> None:
    (api_env.workdir(pid) / "animation" / "assets").mkdir()
    (api_env.workdir(pid) / "animation" / "assets" / "logo.svg").write_text(fx.SVG_RED)
    page = await api_env.client.get(f"{_base(pid)}/")
    sources = re.findall(r'<script src="([^"]+)"', page.text)
    assert "scripts/studio-runtime.js" in sources
    assert "scripts/animation/scenes/s-hook.js" in sources
    for source in sources:
        response = await api_env.client.get(f"{_base(pid)}/{source}")
        assert response.status_code == 200, source
        assert response.headers["content-type"].startswith("text/javascript")
        _assert_preview_headers(response)

    font = await api_env.client.get(f"{_base(pid)}/fonts/anton.woff2")
    assert font.status_code == 200 and font.headers["content-type"] == "font/woff2"
    _assert_preview_headers(font)
    asset = await api_env.client.get(f"{_base(pid)}/assets/logo.svg")
    assert asset.status_code == 200 and asset.headers["content-type"] == "image/svg+xml"
    _assert_preview_headers(asset)


async def test_meta_describes_sections_beats_audio_and_hash(api_env: ApiEnv, pid: str) -> None:
    response = await api_env.client.get(f"{_base(pid)}/meta")
    assert response.status_code == 200, response.text
    _assert_preview_headers(response)
    meta = response.json()
    assert re.fullmatch(r"[0-9a-f]{64}", meta["hash"])
    assert meta["duration"] == pytest.approx(3.0)
    assert [s["id"] for s in meta["sections"]] == ["s-hook", "s-explain"]
    hook = meta["sections"][0]
    assert hook["start"] == 0.0 and hook["end"] == pytest.approx(1.4)
    assert len(hook["beats"]) == 2 and set(hook["beats"][0]) == {"start", "end", "cue_text"}
    assert [a["section_id"] for a in meta["audio"]] == ["s-hook", "s-explain"]
    assert meta["audio"][0]["url"].startswith(
        f"/api/projects/{pid}/files/narrative/audio/s-hook.wav"
    )


async def test_meta_lists_audio_only_for_scenes_that_have_it(api_env: ApiEnv, pid: str) -> None:
    (api_env.workdir(pid) / "narrative" / "audio" / "s-explain.wav").unlink()
    meta = (await api_env.client.get(f"{_base(pid)}/meta")).json()
    assert [a["section_id"] for a in meta["audio"]] == ["s-hook"]


async def _hash(api_env: ApiEnv, pid: str) -> str:
    return (await api_env.client.get(f"{_base(pid)}/meta")).json()["hash"]


async def test_hash_changes_with_scenes_lib_assets_and_timeline_and_is_stable_otherwise(
    api_env: ApiEnv, pid: str
) -> None:
    workdir = api_env.workdir(pid)
    first = await _hash(api_env, pid)
    assert await _hash(api_env, pid) == first

    (workdir / "animation/scenes/s-hook.js").write_text(fx.CUE_SCENE + "// edit\n")
    after_scene = await _hash(api_env, pid)
    (workdir / "animation/lib/colors.js").write_text("const INK = '#000';\n")
    after_lib = await _hash(api_env, pid)
    (workdir / "animation/assets").mkdir()
    (workdir / "animation/assets/logo.svg").write_text(fx.SVG_RED)
    after_asset = await _hash(api_env, pid)
    timing_path = workdir / "narrative/timing.json"
    timing = json.loads(timing_path.read_text())
    timing["scenes"][0]["duration_seconds"] += 0.5
    timing_path.write_text(json.dumps(timing))
    after_timeline = await _hash(api_env, pid)

    assert len({first, after_scene, after_lib, after_asset, after_timeline}) == 5


async def test_page_content_follows_the_workspace_without_a_snapshot(
    api_env: ApiEnv, pid: str
) -> None:
    (api_env.workdir(pid) / "animation/scenes/s-hook.js").write_text(
        "module.exports = { draw() {} }; // FRESH-EDIT\n"
    )
    response = await api_env.client.get(f"{_base(pid)}/scripts/animation/scenes/s-hook.js")
    assert "FRESH-EDIT" in response.text


@pytest.mark.parametrize(
    "bad",
    [
        "..%2f..%2f..%2fetc%2fpasswd",
        "%2e%2e/%2e%2e/secret",
        "scripts/..%2f..%2fx",
        "scripts/animation/scenes/nope.js",
        "assets/nope.svg",
        "fonts/missing.woff2",
        "%2fetc%2fpasswd",
    ],
)
async def test_paths_outside_the_assembled_page_are_404(
    api_env: ApiEnv, pid: str, bad: str
) -> None:
    response = await api_env.client.get(f"{_base(pid)}/{bad}")
    assert response.status_code == 404, bad


async def test_a_symlinked_asset_pointing_outside_the_workspace_is_not_served(
    api_env: ApiEnv, pid: str, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.svg"
    secret.write_text("<svg>SECRET</svg>")
    assets = api_env.workdir(pid) / "animation" / "assets"
    assets.mkdir()
    (assets / "evil.svg").symlink_to(secret)
    response = await api_env.client.get(f"{_base(pid)}/assets/evil.svg")
    assert response.status_code == 404
    assert "SECRET" not in response.text


async def test_unknown_project_is_404(api_env: ApiEnv) -> None:
    for suffix in ("/", "/meta"):
        response = await api_env.client.get(f"{_base('nope')}{suffix}")
        assert response.status_code == 404


async def test_missing_narrative_is_409_with_the_reason(api_env: ApiEnv) -> None:
    created = await api_env.client.post(
        "/api/projects",
        json={"title": "HTML", "engine": "html", "narration": True, "music_source": "none"},
    )
    base = _base(created.json()["id"])
    for suffix in ("/", "/meta"):
        response = await api_env.client.get(f"{base}{suffix}")
        assert response.status_code == 409
        assert "narrative" in assert_detail(response)


async def test_inconsistent_narrative_is_409_naming_the_scene(api_env: ApiEnv, pid: str) -> None:
    timing_path = api_env.workdir(pid) / "narrative/timing.json"
    timing = json.loads(timing_path.read_text())
    timing["scenes"] = timing["scenes"][:1]
    timing_path.write_text(json.dumps(timing))
    response = await api_env.client.get(f"{_base(pid)}/meta")
    assert response.status_code == 409
    assert "s-explain" in assert_detail(response)


async def test_manim_projects_have_no_html_preview(api_env: ApiEnv) -> None:
    manim = seed_animation_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    response = await api_env.client.get(f"{_base(manim)}/meta")
    assert response.status_code == 409
    assert "HTML" in assert_detail(response)


async def test_inline_page_is_self_contained_for_the_sandboxed_iframe(
    api_env: ApiEnv, pid: str
) -> None:
    response = await api_env.client.get(f"{_base(pid)}/inline")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    _assert_preview_headers(response)
    assert "<script src=" not in response.text
    assert "data:font/woff2;base64," in response.text
    assert "window.__PREVIEW__" in response.text and "s-hook" in response.text


async def test_inline_page_follows_the_workspace_and_reports_unavailable_timelines(
    api_env: ApiEnv, pid: str
) -> None:
    (api_env.workdir(pid) / "animation/scenes/s-hook.js").write_text(
        "module.exports = { draw() {} }; // INLINE-EDIT\n"
    )
    assert "INLINE-EDIT" in (await api_env.client.get(f"{_base(pid)}/inline")).text
    (api_env.workdir(pid) / "narrative/timing.json").unlink()
    response = await api_env.client.get(f"{_base(pid)}/inline")
    assert response.status_code == 409 and "timing.json" in assert_detail(response)


async def test_meta_of_a_reel_project_has_music_timeline_sections_and_no_narration_audio(
    api_env: ApiEnv,
) -> None:
    import json

    from studio.db.repo.projects import update_project_settings

    project_id = seed_animation_html_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )
    update_project_settings(
        api_env.app.state.engine,
        project_id,
        {"narration": False, "music_source": "synth", "video_kind": "motion_reel"},
    )
    work = api_env.workdir(project_id)
    bar = 4 * 60 / 128
    (work / "beatsheet").mkdir()
    (work / "beatsheet" / "beatsheet.json").write_text(
        json.dumps(
            {
                "bpm": 128,
                "sections": [
                    {"id": "s1-intro", "label": "INTRO", "bars": 2, "moments": []},
                    {"id": "s2-drop", "label": "DROP", "bars": 2, "moments": []},
                ],
            }
        )
    )
    (work / "music").mkdir()
    (work / "music" / "events.json").write_text(
        json.dumps({"bpm": 128, "duration": 4 * bar, "events": []})
    )
    (work / "music" / "analysis.json").write_text(json.dumps({"hop": 0.1, "energy": [0.5]}))
    fx.write_project(work, scenes={"s1-intro": fx.PURE_SCENE_PLAIN, "s2-drop": fx.PURE_SCENE_PLAIN})

    response = await api_env.client.get(f"{_base(project_id)}/meta")
    assert response.status_code == 200, response.text
    meta = response.json()
    assert [s["id"] for s in meta["sections"]] == ["s1-intro", "s2-drop"]
    assert all(s["beats"] == [] for s in meta["sections"])
    assert meta["audio"] == []
    assert meta["duration"] == pytest.approx(4 * bar)


# ---- the score (3B T4) ------------------------------------------------------------------


async def _scored(api_env: ApiEnv, kind: str):
    from fixtures.synth_music import seed
    from fixtures.synth_music.products import render_products

    engine, blobs = api_env.app.state.engine, api_env.app.state.blobs
    if kind == "reel":
        project_id = seed.seed_reel_project(engine, blobs, data_dir=api_env.data_dir)
        work = api_env.workdir(project_id)
        (work / "beatsheet").mkdir()
        (work / "beatsheet" / "beatsheet.json").write_text(seed.BEATSHEET, encoding="utf-8")
        scenes = ["s1", "s2"]
    else:
        project_id = seed.seed_bed_project(engine, blobs, data_dir=api_env.data_dir)
        work = api_env.workdir(project_id)
        scenes = ["s-hook", "s-explain"]
    await render_products(work)
    fx.write_project(work, scenes={name: fx.PURE_SCENE_PLAIN for name in scenes})
    return project_id, work


async def test_meta_points_a_reel_at_its_score_at_full_gain(api_env: ApiEnv) -> None:
    pid, work = await _scored(api_env, "reel")
    meta = (await api_env.client.get(f"{_base(pid)}/meta")).json()
    wav_hash = json.loads((work / "music" / "render.json").read_text())["wav_hash"]
    assert meta["music"] == {
        "url": f"/api/projects/{pid}/music/audio?v={wav_hash}",
        "gain": 1.0,
    }
    assert meta["audio"] == []


async def test_meta_gives_an_explainer_bed_its_quieter_gain_next_to_the_narration(
    api_env: ApiEnv,
) -> None:
    pid, _ = await _scored(api_env, "bed")
    meta = (await api_env.client.get(f"{_base(pid)}/meta")).json()
    assert meta["music"]["gain"] == pytest.approx(10 ** (-8 / 20))
    assert len(meta["audio"]) == 2


async def test_meta_has_no_music_when_nothing_is_rendered_or_the_score_is_stale(
    api_env: ApiEnv,
) -> None:
    pid, work = await _scored(api_env, "reel")
    path = work / "beatsheet" / "beatsheet.json"
    path.write_text(path.read_text().replace("BUILD", "RISE", 1), encoding="utf-8")
    assert (await api_env.client.get(f"{_base(pid)}/meta")).json()["music"] is None

    (work / "music" / "render.json").unlink()
    assert (await api_env.client.get(f"{_base(pid)}/meta")).json()["music"] is None


async def test_meta_of_an_explainer_without_music_has_no_music_field_value(
    api_env: ApiEnv, pid: str
) -> None:
    assert (await api_env.client.get(f"{_base(pid)}/meta")).json()["music"] is None
