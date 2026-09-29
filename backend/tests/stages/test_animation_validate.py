"""`stages.animation.validate_scenes`（设计 §5.3；计划 T7）。

用 T4 的 `animation_project` fixture（顶层 `conftest.py`，D13）取一个"叙事
已定稿"的项目，手动 `materialize_upstream` 出 `upstream/narrative/`（模拟
`TurnRunner` 在轮次开始前做的事），再直接往 `animation/scenes/` 写镜头代码
（绕过 `WriteScope`，因为这里模拟的是"测试提前准备好的文件"而不是走
agent 的写入路径，`fixtures/animation/seed.py` 对 `narrative/` 也是同样
做法）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pytest
from sqlalchemy import Engine

from studio.agent.stage_flow import upstream_sources
from studio.agent.tools import ToolContext, invoke_tool
from studio.stages.animation import STAGE as ANIMATION_STAGE
from studio.stages.animation.validate_scenes import VALIDATE_SCENES_TOOL
from studio.workspace import BlobStore, materialize_upstream


class AnimationProjectEnv(Protocol):
    """`conftest.AnimationProjectEnv` 的结构类型（鸭子类型），不直接
    `from conftest import AnimationProjectEnv`——本文件在 `tests/stages/`
    包内（有 `__init__.py`），pyright 解析裸的 `import conftest` 会优先
    匹配同目录下的 `tests/stages/conftest.py`（没有这个类），而不是 pytest
    运行时实际用到的顶层 `tests/conftest.py`（rootdir 插入的是 `tests/`，
    两者对同一个模块名解析出不同结果）。用结构类型描述这个 fixture 实际
    用到的字段，避免这个静态检查和运行时的分歧。
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
    sources = upstream_sources(env.engine, env.project_id, ANIMATION_STAGE)
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
    assert VALIDATE_SCENES_TOOL.stages == {"animation"}


@pytest.mark.slow
async def test_all_valid_scenes_pass(animation_project: AnimationProjectEnv) -> None:
    _materialize(animation_project)
    for scene_id, code in _VALID_CODE.items():
        _write_scene(animation_project, scene_id, code)

    result = await invoke_tool(VALIDATE_SCENES_TOOL, _ctx(animation_project), {})

    assert result.is_error is False
    assert "2" in result.text
    assert "通过" in result.text


async def test_missing_scene_file_is_reported_by_scene_id(
    animation_project: AnimationProjectEnv,
) -> None:
    _materialize(animation_project)
    _write_scene(animation_project, "s-hook", _VALID_CODE["s-hook"])
    # s-explain.py 不写，模拟"还没写这个镜头"。

    result = await invoke_tool(VALIDATE_SCENES_TOOL, _ctx(animation_project), {})

    assert result.is_error is True
    assert "s-explain" in result.text
    assert "s-hook" not in result.text


async def test_empty_scene_file_is_treated_as_missing(
    animation_project: AnimationProjectEnv,
) -> None:
    _materialize(animation_project)
    _write_scene(animation_project, "s-hook", _VALID_CODE["s-hook"])
    _write_scene(animation_project, "s-explain", "   \n")

    result = await invoke_tool(VALIDATE_SCENES_TOOL, _ctx(animation_project), {})

    assert result.is_error is True
    assert "s-explain" in result.text


async def test_syntax_error_is_reported_by_scene_id(
    animation_project: AnimationProjectEnv,
) -> None:
    _materialize(animation_project)
    _write_scene(animation_project, "s-hook", _VALID_CODE["s-hook"])
    _write_scene(animation_project, "s-explain", "x = [1, 2\nself.wait(1)")

    result = await invoke_tool(VALIDATE_SCENES_TOOL, _ctx(animation_project), {})

    assert result.is_error is True
    assert "s-explain" in result.text
    assert "SyntaxError" in result.text
    assert "s-hook" not in result.text


async def test_narrative_json_missing_is_a_tool_error(workdir: Path) -> None:
    """`upstream/narrative/narrative.json` 还没物化时，工具报 `is_error` 而不是
    让 `FileNotFoundError` 直接从 handler 里冒出去——这条路径由 `invoke_tool`
    统一兜底（设计 §4.2），`validate_scenes` 本身不用专门处理这种情况。"""
    ctx = ToolContext(
        project_id="proj-1",
        stage="animation",
        workdir=workdir,
        record_tool_write=lambda relpath, sha256: None,
    )

    result = await invoke_tool(VALIDATE_SCENES_TOOL, ctx, {})

    assert result.is_error is True
    assert "工具执行出错" in result.text
