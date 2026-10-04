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
