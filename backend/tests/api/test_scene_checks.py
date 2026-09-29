"""`compute_scene_checks`（TD-33）：从 `turn_events`/`turns`/`snapshots` 读时
聚合出每个镜头最近一次 `validate_scenes`/`render_preview` 的状态，不新增表。

直接用 repo 函数搭最小可信的持久化数据（会话/turn/事件/快照），不经过完整
的 agent runtime——被测函数只关心这些表里已经落库的形状。
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import Engine

from studio.api.scene_checks import compute_scene_checks
from studio.db.repo.sessions import create_session
from studio.db.repo.snapshots import insert_snapshot
from studio.db.repo.turns import append_event, create_turn_if_session_idle, finish_turn


class AnimationProjectEnv(Protocol):
    """`conftest.AnimationProjectEnv` 的结构类型；不直接
    `from conftest import AnimationProjectEnv`——见决策记录 D25、
    `tests/stages/test_animation_preview.py` 顶部同名类型的说明：这个目录
    下会遇到同样的 pyright/pytest 模块解析分歧，各自定义一份绕开。
    """

    project_id: str
    engine: Engine


def _session(engine: Engine, project_id: str) -> str:
    return create_session(
        engine,
        project_id=project_id,
        stage="animation",
        model_profile_id="fake-profile",
        runtime="fake",
    ).id


def _turn_with_check(
    engine: Engine,
    *,
    session_id: str,
    project_id: str,
    call_id: str,
    name: str,
    args: dict[str, object],
    result_text: str,
    is_error: bool,
    end_manifest: dict[str, str],
) -> None:
    """跑一个只含一次工具调用的最小 turn：`tool_call` + `tool_result` +
    一条 `end_snapshot_id` 指向 `end_manifest` 的快照，模拟一轮真实对话
    结束时"这一轮结束时工作区长什么样"。
    """
    turn = create_turn_if_session_idle(engine, session_id, "嗯")
    assert turn is not None
    # Real `TurnRunner._persist` prepends `turn_id` to every persisted
    # event's payload (see `runner.py::_persist`); replicate that here since
    # `compute_scene_checks` reads it off the `tool_result` payload.
    append_event(
        engine,
        turn_id=turn.id,
        session_id=session_id,
        type="tool_call",
        payload={"turn_id": turn.id, "call_id": call_id, "name": name, "args": args},
    )
    append_event(
        engine,
        turn_id=turn.id,
        session_id=session_id,
        type="tool_result",
        payload={
            "turn_id": turn.id,
            "call_id": call_id,
            "text": result_text,
            "is_error": is_error,
        },
    )
    snapshot = insert_snapshot(engine, project_id=project_id, manifest=end_manifest, reason="turn")
    finish_turn(
        engine,
        turn.id,
        status="done",
        end_snapshot_id=snapshot.id,
        usage=None,
        cost_usd=None,
        error=None,
        resume_ref=None,
    )


def _set_current_manifest(engine: Engine, project_id: str, manifest: dict[str, str]) -> None:
    insert_snapshot(engine, project_id=project_id, manifest=manifest, reason="user_edit")


class TestNotChecked:
    def test_scene_never_checked_is_not_checked(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        result = compute_scene_checks(
            animation_project.engine, animation_project.project_id, ["s-hook"]
        )

        assert result["s-hook"].validate_scenes.status == "not_checked"
        assert result["s-hook"].render_preview.status == "not_checked"


class TestValidatePassed:
    def test_all_passed_applies_to_every_known_scene(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        engine, project_id = animation_project.engine, animation_project.project_id
        session_id = _session(engine, project_id)
        manifest = {"animation/scenes/s-hook.py": "sha-a", "animation/scenes/s-explain.py": "sha-b"}
        _turn_with_check(
            engine,
            session_id=session_id,
            project_id=project_id,
            call_id="c1",
            name="validate_scenes",
            args={},
            result_text="全部 2 个镜头静态校验通过。",
            is_error=False,
            end_manifest=manifest,
        )
        _set_current_manifest(engine, project_id, manifest)

        result = compute_scene_checks(engine, project_id, ["s-hook", "s-explain"])

        assert result["s-hook"].validate_scenes.status == "passed"
        assert result["s-hook"].validate_scenes.stale is False
        assert result["s-explain"].validate_scenes.status == "passed"


class TestValidateFailure:
    def test_named_scene_fails_others_still_pass(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        engine, project_id = animation_project.engine, animation_project.project_id
        session_id = _session(engine, project_id)
        manifest = {"animation/scenes/s-hook.py": "sha-a", "animation/scenes/s-explain.py": "sha-b"}
        # First an all-passed check, then a later one naming only s-hook as broken.
        _turn_with_check(
            engine,
            session_id=session_id,
            project_id=project_id,
            call_id="c1",
            name="validate_scenes",
            args={},
            result_text="全部 2 个镜头静态校验通过。",
            is_error=False,
            end_manifest=manifest,
        )
        _turn_with_check(
            engine,
            session_id=session_id,
            project_id=project_id,
            call_id="c2",
            name="validate_scenes",
            args={},
            result_text="镜头 s-hook（scene 0）: NameError: 'Foo' is not defined",
            is_error=True,
            end_manifest=manifest,
        )
        _set_current_manifest(engine, project_id, manifest)

        result = compute_scene_checks(engine, project_id, ["s-hook", "s-explain"])

        assert result["s-hook"].validate_scenes.status == "failed"
        assert result["s-explain"].validate_scenes.status == "passed"

    def test_missing_code_message_names_scenes(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        engine, project_id = animation_project.engine, animation_project.project_id
        session_id = _session(engine, project_id)
        manifest = {"animation/scenes/s-hook.py": "sha-a"}
        _turn_with_check(
            engine,
            session_id=session_id,
            project_id=project_id,
            call_id="c1",
            name="validate_scenes",
            args={},
            result_text="以下镜头缺少代码或代码为空，需要先写好再校验：s-explain",
            is_error=True,
            end_manifest=manifest,
        )
        _set_current_manifest(engine, project_id, manifest)

        result = compute_scene_checks(engine, project_id, ["s-explain"])

        assert result["s-explain"].validate_scenes.status == "failed"

    def test_newer_all_passed_overrides_older_failure(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        engine, project_id = animation_project.engine, animation_project.project_id
        session_id = _session(engine, project_id)
        manifest = {"animation/scenes/s-hook.py": "sha-a"}
        _turn_with_check(
            engine,
            session_id=session_id,
            project_id=project_id,
            call_id="c1",
            name="validate_scenes",
            args={},
            result_text="镜头 s-hook（scene 0）: NameError",
            is_error=True,
            end_manifest=manifest,
        )
        _turn_with_check(
            engine,
            session_id=session_id,
            project_id=project_id,
            call_id="c2",
            name="validate_scenes",
            args={},
            result_text="全部 1 个镜头静态校验通过。",
            is_error=False,
            end_manifest=manifest,
        )
        _set_current_manifest(engine, project_id, manifest)

        result = compute_scene_checks(engine, project_id, ["s-hook"])

        assert result["s-hook"].validate_scenes.status == "passed"


class TestPreview:
    def test_preview_is_scoped_to_its_own_scene(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        engine, project_id = animation_project.engine, animation_project.project_id
        session_id = _session(engine, project_id)
        manifest = {"animation/scenes/s-hook.py": "sha-a", "animation/scenes/s-explain.py": "sha-b"}
        _turn_with_check(
            engine,
            session_id=session_id,
            project_id=project_id,
            call_id="c1",
            name="render_preview",
            args={"scene_id": "s-hook"},
            result_text="镜头 s-hook 预览渲染完成。",
            is_error=False,
            end_manifest=manifest,
        )
        _set_current_manifest(engine, project_id, manifest)

        result = compute_scene_checks(engine, project_id, ["s-hook", "s-explain"])

        assert result["s-hook"].render_preview.status == "passed"
        assert result["s-explain"].render_preview.status == "not_checked"

    def test_failed_preview_is_reported(self, animation_project: AnimationProjectEnv) -> None:
        engine, project_id = animation_project.engine, animation_project.project_id
        session_id = _session(engine, project_id)
        manifest = {"animation/scenes/s-hook.py": "sha-a"}
        _turn_with_check(
            engine,
            session_id=session_id,
            project_id=project_id,
            call_id="c1",
            name="render_preview",
            args={"scene_id": "s-hook"},
            result_text="预览渲染失败。",
            is_error=True,
            end_manifest=manifest,
        )
        _set_current_manifest(engine, project_id, manifest)

        result = compute_scene_checks(engine, project_id, ["s-hook"])

        assert result["s-hook"].render_preview.status == "failed"


class TestStale:
    def test_code_changed_after_check_is_stale(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        engine, project_id = animation_project.engine, animation_project.project_id
        session_id = _session(engine, project_id)
        checked_manifest = {"animation/scenes/s-hook.py": "sha-old"}
        _turn_with_check(
            engine,
            session_id=session_id,
            project_id=project_id,
            call_id="c1",
            name="render_preview",
            args={"scene_id": "s-hook"},
            result_text="ok",
            is_error=False,
            end_manifest=checked_manifest,
        )
        # The scene's code changed after the check ran.
        _set_current_manifest(engine, project_id, {"animation/scenes/s-hook.py": "sha-new"})

        result = compute_scene_checks(engine, project_id, ["s-hook"])

        assert result["s-hook"].render_preview.status == "passed"
        assert result["s-hook"].render_preview.stale is True

    def test_unchanged_code_is_not_stale(self, animation_project: AnimationProjectEnv) -> None:
        engine, project_id = animation_project.engine, animation_project.project_id
        session_id = _session(engine, project_id)
        manifest = {"animation/scenes/s-hook.py": "sha-same"}
        _turn_with_check(
            engine,
            session_id=session_id,
            project_id=project_id,
            call_id="c1",
            name="render_preview",
            args={"scene_id": "s-hook"},
            result_text="ok",
            is_error=False,
            end_manifest=manifest,
        )
        _set_current_manifest(engine, project_id, manifest)

        result = compute_scene_checks(engine, project_id, ["s-hook"])

        assert result["s-hook"].render_preview.stale is False


class TestMultipleSessions:
    def test_checks_across_two_sessions_are_merged_by_time(
        self, animation_project: AnimationProjectEnv
    ) -> None:
        # T7 T13: a project's animation stage can have more than one session
        # (e.g. switching models); checks must be merged chronologically, not
        # per-session.
        engine, project_id = animation_project.engine, animation_project.project_id
        session_a = _session(engine, project_id)
        session_b = _session(engine, project_id)
        manifest = {"animation/scenes/s-hook.py": "sha-a"}
        _turn_with_check(
            engine,
            session_id=session_a,
            project_id=project_id,
            call_id="c1",
            name="render_preview",
            args={"scene_id": "s-hook"},
            result_text="失败",
            is_error=True,
            end_manifest=manifest,
        )
        _turn_with_check(
            engine,
            session_id=session_b,
            project_id=project_id,
            call_id="c2",
            name="render_preview",
            args={"scene_id": "s-hook"},
            result_text="成功",
            is_error=False,
            end_manifest=manifest,
        )
        _set_current_manifest(engine, project_id, manifest)

        result = compute_scene_checks(engine, project_id, ["s-hook"])

        assert result["s-hook"].render_preview.status == "passed"
