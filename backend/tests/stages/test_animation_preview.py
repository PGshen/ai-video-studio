"""`stages.animation.render_preview`（设计 §5.3；计划 T8）。

用 T4 的 `animation_project` fixture（顶层 `conftest.py`，D13）取一个"叙事
已定稿"的项目，手动 `materialize_upstream` 出 `upstream/narrative/`（模拟
`TurnRunner` 在轮次开始前做的事），再直接往 `animation/scenes/` 写镜头代码
（同 `test_animation_validate.py` 的做法）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pytest
from sqlalchemy import Engine

from fixtures.animation.seed import fixture_registry
from studio.agent.stage_flow import upstream_sources
from studio.agent.tools import ToolContext, invoke_tool
from studio.engines.render.base import PreviewResult
from studio.engines.render.manim import ManimRenderEngine
from studio.stages.animation import STAGE as ANIMATION_STAGE
from studio.stages.animation.render_preview import RENDER_PREVIEW_TOOL
from studio.workspace import BlobStore, materialize_upstream


class AnimationProjectEnv(Protocol):
    """`conftest.AnimationProjectEnv` 的结构类型；不直接
    `from conftest import AnimationProjectEnv`——见决策记录 D25、
    `test_animation_validate.py` 顶部同名类型的说明，本文件在同一个
    目录下会遇到同样的 pyright/pytest 模块解析分歧，各自定义一份绕开，
    避免测试文件之间产生额外耦合。
    """

    project_id: str
    workdir: Path
    engine: Engine
    blobs: BlobStore


_VALID_CODE = {
    "s-hook": "self.add(Dot())",
    "s-explain": "self.add(Square())",
}


def _materialize(env: AnimationProjectEnv) -> None:
    sources = upstream_sources(env.engine, fixture_registry(), env.project_id, ANIMATION_STAGE.name)
    materialize_upstream(env.workdir, env.blobs, sources)


def _write_scene(env: AnimationProjectEnv, scene_id: str, code: str) -> None:
    scenes_dir = env.workdir / "animation" / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    (scenes_dir / f"{scene_id}.py").write_text(code, encoding="utf-8")


def _ctx(env: AnimationProjectEnv) -> ToolContext:
    return ToolContext(
        project_id=env.project_id,
        stage="animation",
        workdir=env.workdir,
        record_tool_write=lambda relpath, sha256: None,
    )


def test_tool_is_scoped_to_animation_stage() -> None:
    assert RENDER_PREVIEW_TOOL.stages == {"animation"}


@pytest.mark.slow
async def test_render_preview_returns_one_image_per_beat_and_deviation_text(
    animation_project: AnimationProjectEnv,
) -> None:
    _materialize(animation_project)
    for scene_id, code in _VALID_CODE.items():
        _write_scene(animation_project, scene_id, code)

    result = await invoke_tool(
        RENDER_PREVIEW_TOOL, _ctx(animation_project), {"scene_id": "s-explain"}
    )

    assert result.is_error is False, result.text
    # fixture 里 s-explain 有 2 个 beat（backend/tests/fixtures/animation/timing.json）。
    assert len(result.images) == 2
    assert all(image.media_type == "image/jpeg" for image in result.images)
    assert all(image.data_base64 for image in result.images)
    assert "s-explain" in result.text
    assert "偏差" in result.text


async def test_unknown_scene_id_is_a_tool_error(animation_project: AnimationProjectEnv) -> None:
    _materialize(animation_project)
    for scene_id, code in _VALID_CODE.items():
        _write_scene(animation_project, scene_id, code)

    result = await invoke_tool(
        RENDER_PREVIEW_TOOL, _ctx(animation_project), {"scene_id": "s-nonexistent"}
    )

    assert result.is_error is True
    assert "s-nonexistent" in result.text


async def test_missing_scene_code_is_reported_by_scene_id(
    animation_project: AnimationProjectEnv,
) -> None:
    _materialize(animation_project)
    # s-explain.py 不写，模拟"还没写这个镜头就想预览它"。

    result = await invoke_tool(
        RENDER_PREVIEW_TOOL, _ctx(animation_project), {"scene_id": "s-explain"}
    )

    assert result.is_error is True
    assert "s-explain" in result.text


async def test_engine_timeout_becomes_tool_error(
    animation_project: AnimationProjectEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """引擎超时时（`ManimRenderEngine.render_preview` 返回
    `success=False, error_message="预览渲染超时"`，行为已由 T2 的
    `test_render_preview_times_out_without_waiting_120_seconds` 覆盖），
    本工具层只需要保证原样转成 `is_error=True` 的 `ToolResult`，不用真的
    等一次超时渲染。"""
    _materialize(animation_project)
    for scene_id, code in _VALID_CODE.items():
        _write_scene(animation_project, scene_id, code)

    async def _fake_render_preview(self: ManimRenderEngine, request, timeout_seconds=None):
        return PreviewResult(
            success=False,
            error_message="预览渲染超时",
            render_duration_seconds=None,
            duration_deviation_seconds=None,
            keyframes=[],
            render_log="",
        )

    monkeypatch.setattr(ManimRenderEngine, "render_preview", _fake_render_preview)

    result = await invoke_tool(
        RENDER_PREVIEW_TOOL, _ctx(animation_project), {"scene_id": "s-explain"}
    )

    assert result.is_error is True
    assert result.text == "预览渲染超时"
    assert result.images == []


async def test_noisy_keyframes_stay_well_under_the_sdk_message_limit(
    animation_project: AnimationProjectEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Claude SDK drops one JSON message over 1 MiB (found by the 3A real-model smoke run):
    the keyframes of one preview, all in one tool result, are returned as small JPEGs."""
    import base64
    import io

    import numpy as np
    from PIL import Image

    from studio.engines.render.base import PreviewKeyframe

    _materialize(animation_project)
    for scene_id, code in _VALID_CODE.items():
        _write_scene(animation_project, scene_id, code)
    rng = np.random.default_rng(5)

    def noisy_png() -> bytes:
        buffer = io.BytesIO()
        pixels = rng.integers(0, 256, (720, 1280, 3), dtype=np.uint8)
        Image.fromarray(pixels).save(buffer, format="PNG")
        return buffer.getvalue()

    keyframes = [PreviewKeyframe(beat_index=i, png_bytes=noisy_png()) for i in range(6)]

    async def _fake(self: ManimRenderEngine, request, timeout_seconds=None):
        return PreviewResult(True, None, 1.0, 0.0, keyframes, "")

    monkeypatch.setattr(ManimRenderEngine, "render_preview", _fake)
    result = await invoke_tool(
        RENDER_PREVIEW_TOOL, _ctx(animation_project), {"scene_id": "s-explain"}
    )
    assert result.is_error is False, result.text
    assert len(result.images) == 6 and all(i.media_type == "image/jpeg" for i in result.images)
    total = sum(len(base64.b64decode(i.data_base64)) for i in result.images)
    assert total <= 700_000, total
    assert all(base64.b64decode(i.data_base64)[:3] == b"\xff\xd8\xff" for i in result.images)
