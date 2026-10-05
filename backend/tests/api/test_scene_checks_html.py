"""`compute_scene_checks` 对 `animation_html` 项目生效（2B T4）：两个 HTML 工具、`.js` 镜头路径。

归属规则（输出形状见 `validate_scenes_html` 顶部文档）：带 `scene_id` 的校验只属于该镜头；
不带的成功是项目级通过；不带的失败按行首 `镜头 <id>：` 点名，没有点名（页面级错误）则全部镜头失败。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import Engine

from fixtures.animation_html.seed import seed_animation_html_project
from studio.api.scene_checks import compute_scene_checks
from studio.db.engine import make_engine, migrate
from studio.db.repo.sessions import create_session
from studio.db.repo.snapshots import insert_snapshot
from studio.db.repo.turns import append_event, create_turn_if_session_idle, finish_turn
from studio.workspace import BlobStore

SCENES = ["s-hook", "s-explain"]
MANIFEST = {"animation/scenes/s-hook.js": "sha-a", "animation/scenes/s-explain.js": "sha-b"}


@dataclass
class Env:
    engine: Engine
    project_id: str
    session_id: str


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    engine = make_engine(tmp_path / "studio.db")
    migrate(engine)
    project_id = seed_animation_html_project(
        engine, BlobStore(tmp_path / "data" / "blobs"), data_dir=tmp_path / "data"
    )
    session = create_session(
        engine,
        project_id=project_id,
        stage="animation_html",
        model_profile_id="fake-profile",
        runtime="fake",
    )
    yield Env(engine, project_id, session.id)
    engine.dispose()


def _check(
    env: Env,
    *,
    name: str,
    args: dict[str, object],
    text: str,
    is_error: bool,
    manifest: dict[str, str] = MANIFEST,
    images: list[str] | None = None,
    call_id: str = "c",
) -> None:
    turn = create_turn_if_session_idle(env.engine, env.session_id, "嗯")
    assert turn is not None
    append_event(
        env.engine,
        turn_id=turn.id,
        session_id=env.session_id,
        type="tool_call",
        payload={"turn_id": turn.id, "call_id": call_id, "name": name, "args": args},
    )
    append_event(
        env.engine,
        turn_id=turn.id,
        session_id=env.session_id,
        type="tool_result",
        payload={
            "turn_id": turn.id,
            "call_id": call_id,
            "text": text,
            "is_error": is_error,
            "images": [{"media_type": "image/jpeg", "sha256": sha} for sha in images or []],
        },
    )
    snapshot = insert_snapshot(
        env.engine, project_id=env.project_id, manifest=manifest, reason="turn"
    )
    finish_turn(
        env.engine,
        turn.id,
        status="done",
        end_snapshot_id=snapshot.id,
        usage=None,
        cost_usd=None,
        error=None,
        resume_ref=None,
    )
    insert_snapshot(env.engine, project_id=env.project_id, manifest=manifest, reason="user_edit")


def _checks(env: Env):
    return compute_scene_checks(env.engine, env.project_id, SCENES)


def test_never_checked_is_not_checked(env: Env) -> None:
    result = _checks(env)
    assert result["s-hook"].validate_scenes.status == "not_checked"
    assert result["s-hook"].render_preview.status == "not_checked"


def test_all_passed_applies_to_every_scene(env: Env) -> None:
    _check(
        env,
        name="validate_scenes_html",
        args={},
        text="全部 2 个镜头校验通过。\n警告 镜头 s-hook：字符 龘 不在内置字体里",
        is_error=False,
    )
    result = _checks(env)
    assert [result[s].validate_scenes.status for s in SCENES] == ["passed", "passed"]
    assert result["s-hook"].validate_scenes.stale is False


def test_single_scene_validation_only_belongs_to_that_scene(env: Env) -> None:
    _check(
        env,
        name="validate_scenes_html",
        args={"scene_id": "s-explain"},
        text="镜头 s-explain 校验通过。",
        is_error=False,
    )
    result = _checks(env)
    assert result["s-explain"].validate_scenes.status == "passed"
    assert result["s-hook"].validate_scenes.status == "not_checked"


def test_single_scene_failure_only_marks_that_scene(env: Env) -> None:
    _check(
        env,
        name="validate_scenes_html",
        args={},
        text="全部 2 个镜头校验通过。",
        is_error=False,
        call_id="c1",
    )
    _check(
        env,
        name="validate_scenes_html",
        args={"scene_id": "s-hook"},
        text="镜头 s-hook：渲染超时\n共 1 个错误、0 个警告。",
        is_error=True,
        call_id="c2",
    )
    result = _checks(env)
    assert result["s-hook"].validate_scenes.status == "failed"
    assert result["s-explain"].validate_scenes.status == "passed"


def test_full_failure_names_scenes_by_line_prefix_and_ignores_warning_lines(env: Env) -> None:
    _check(
        env,
        name="validate_scenes_html",
        args={},
        text=(
            "镜头 s-explain：整个镜头对任何旁白 beat 都无反应\n"
            "警告 镜头 s-hook：env.cue(1) 对应的 beat 没有驱动画面\n"
            "共 1 个错误、1 个警告。"
        ),
        is_error=True,
    )
    result = _checks(env)
    assert result["s-explain"].validate_scenes.status == "failed"
    assert result["s-hook"].validate_scenes.status == "not_checked"


def test_page_level_failure_without_a_named_scene_fails_every_scene(env: Env) -> None:
    _check(
        env,
        name="validate_scenes_html",
        args={},
        text="时间轴不可用：narrative/timing.json 不存在",
        is_error=True,
    )
    result = _checks(env)
    assert [result[s].validate_scenes.status for s in SCENES] == ["failed", "failed"]


def test_preview_is_scoped_to_its_scene_and_exposes_images(env: Env) -> None:
    _check(
        env,
        name="render_preview_html",
        args={"scene_id": "s-hook"},
        text="镜头 s-hook 预览：16 帧",
        is_error=False,
        images=["img-1"],
    )
    result = _checks(env)
    assert result["s-hook"].render_preview.status == "passed"
    assert result["s-hook"].render_preview.images == ("img-1",)
    assert result["s-explain"].render_preview.status == "not_checked"


def test_manim_tool_names_are_ignored_for_html_projects(env: Env) -> None:
    _check(
        env,
        name="validate_scenes",
        args={},
        text="全部 2 个镜头静态校验通过。",
        is_error=False,
    )
    assert _checks(env)["s-hook"].validate_scenes.status == "not_checked"


def test_scene_edited_after_the_check_is_stale(env: Env) -> None:
    _check(
        env,
        name="validate_scenes_html",
        args={},
        text="全部 2 个镜头校验通过。",
        is_error=False,
    )
    insert_snapshot(
        env.engine,
        project_id=env.project_id,
        manifest={**MANIFEST, "animation/scenes/s-hook.js": "sha-changed"},
        reason="user_edit",
    )
    result = _checks(env)
    assert result["s-hook"].validate_scenes.stale is True
    assert result["s-explain"].validate_scenes.stale is False
