"""`explainer_html` 项目从预览到成片到定稿（2B T8，真实 Chromium 与 ffmpeg，`-m slow`）。

fixture 项目（叙事已定稿，两个镜头共 3 秒，带配音）→ 写入镜头脚本 → 预览端点能服务页面与资源 →
`POST /render` → worker 渲染 → `output/final.mp4`（H.264 视频加 AAC 旁白）与 `final.json` → 定稿。
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

import pytest

from fixtures.animation_html.seed import seed_animation_html_project
from fixtures.html_engine import projects as fx
from studio.worker import run_once

from .conftest import ApiEnv

pytestmark = pytest.mark.slow


def _probe(path: Any) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


async def test_preview_render_and_finalize_an_html_project(api_env: ApiEnv) -> None:
    engine = api_env.app.state.engine
    blobs = api_env.app.state.blobs
    pid = seed_animation_html_project(engine, blobs, data_dir=api_env.data_dir)
    fx.write_project(
        api_env.workdir(pid),
        scenes={"s-hook": fx.CUE_SCENE, "s-explain": fx.CUE_SCENE},
        lib={"colors": "const INK = '#fff';\n"},
    )
    client = api_env.client
    base = f"/api/projects/{pid}/animation/html-preview"

    # 1. 预览端点：页面、它引用的每个脚本、字体都能取到；meta 与时间轴一致。
    page = await client.get(f"{base}/")
    assert page.status_code == 200
    for source in re.findall(r'<script src="([^"]+)"', page.text):
        assert (await client.get(f"{base}/{source}")).status_code == 200, source
    assert (await client.get(f"{base}/fonts/notosanssc-400.woff2")).status_code == 200
    meta = (await client.get(f"{base}/meta")).json()
    assert meta["duration"] == pytest.approx(3.0)

    # 2. 创建渲染任务，worker 渲染（真实 Chromium + ffmpeg）。
    created = await client.post(f"/api/projects/{pid}/render")
    assert created.status_code == 201
    assert await run_once(engine, blobs, data_dir=api_env.data_dir) is True
    job = (await client.get(f"/api/projects/{pid}/jobs/{created.json()['id']}")).json()
    assert job["status"] == "done", job["error"]

    # 3. 成片：1920×1080 H.264，加 AAC 旁白，时长等于时间轴。
    final = api_env.workdir(pid) / "output" / "final.mp4"
    info = _probe(final)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (video["codec_name"], video["width"], video["height"]) == ("h264", 1920, 1080)
    assert audio["codec_name"] == "aac"
    assert abs(float(info["format"]["duration"]) - 3.0) < 0.1

    meta_json = json.loads((api_env.workdir(pid) / "output" / "final.json").read_text())
    assert meta_json["engine"] == "html"
    assert set(meta_json["audio_sources"]) == {"s-hook", "s-explain"}
    download = await client.get(f"/api/projects/{pid}/output/final.mp4")
    assert download.status_code == 200 and len(download.content) == final.stat().st_size

    # 4. 定稿：阶段 `animation_html` 完成，项目完成。
    finalized = await client.post(f"/api/projects/{pid}/animation/finalize-render")
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["stage"] == "animation_html"
    assert (await client.get(f"/api/projects/{pid}")).json()["completed_at"] is not None


async def test_a_scene_that_throws_fails_the_job_with_the_scene_and_time(api_env: ApiEnv) -> None:
    engine = api_env.app.state.engine
    blobs = api_env.app.state.blobs
    pid = seed_animation_html_project(engine, blobs, data_dir=api_env.data_dir)
    fx.write_project(
        api_env.workdir(pid),
        scenes={
            "s-hook": fx.CUE_SCENE,
            "s-explain": (
                "module.exports = { draw(ctx, lt, env) {"
                " env.cue(0); if (lt > 0.5) throw new Error('late failure'); } };\n"
            ),
        },
    )
    created = await api_env.client.post(f"/api/projects/{pid}/render")
    await run_once(engine, blobs, data_dir=api_env.data_dir)
    job = (await api_env.client.get(f"/api/projects/{pid}/jobs/{created.json()['id']}")).json()
    assert job["status"] == "failed"
    assert "s-explain" in job["error"] and "late failure" in job["error"]
    assert not (api_env.workdir(pid) / "output" / "final.mp4").exists()
