"""端到端集成测试（M2 T14）：串联 T4–T11 的产物，验证 AC4。

不重新测试任何单个工具/端点/引擎方法自身的正确性——那些都已经在
T1/T2/T7/T8/T10/T11 各自的测试里覆盖过。这条测试只验证"把它们串成一条
真实链路"这件事本身没问题：

叙事定稿（T4 fixture）→ animation agent（真实 `TurnRunner` + `FakeRuntime`）
跑一轮，写两个镜头代码并在轮次内调用 `validate_scenes`/`render_preview`
（T7/T8 的工具，验证的是"在一轮真实 turn 里调用"这条路径，不是工具本身）
→ `POST /render`（T10）创建 `final_render` 任务 → `worker.run_once`（T5，
直接调用同一个函数，不起真实进程）产出成片 → `POST
/animation/finalize-render`（T11）成片定稿，阶段变 `finalized`、项目
`completed_at` 非空。

全程真实起 manim/ffmpeg 子进程（渲染两次预览关键帧 + 两个镜头的全画质
渲染），标 `@pytest.mark.slow`。
"""

from __future__ import annotations

import pytest

from fixtures.animation.seed import seed_animation_project
from studio.agent.fake import FakeRuntime, call_tool, write
from studio.agent.runtime import UserInput
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.turns import get_turn, list_events
from studio.worker import run_once

from .conftest import ApiEnv

_SCENE_CODES = {
    "s-hook": "self.add(Dot())",
    "s-explain": "self.add(Square())",
}


async def _animation_project(api_env: ApiEnv) -> str:
    """叙事已定稿、动画阶段 `active` 的项目（复用 T4 的种子脚本，绕过 M3）。"""
    return seed_animation_project(
        api_env.app.state.engine, api_env.app.state.blobs, data_dir=api_env.data_dir
    )


@pytest.mark.slow
class TestAnimationEndToEndFlow:
    async def test_narrative_to_finalized_render(self, api_env: ApiEnv) -> None:
        pid = await _animation_project(api_env)
        engine = api_env.app.state.engine

        # ------------------------------------------------------------------
        # 1. animation agent（FakeRuntime）跑一轮：写两个镜头代码，轮次内
        #    依次调用 validate_scenes（预期通过）和 render_preview（对
        #    s-explain，预期返回该镜头 beat 数量的关键帧）。
        # ------------------------------------------------------------------
        profile = get_model_profile(engine, "fake")
        assert profile is not None
        session = create_session(
            engine,
            project_id=pid,
            stage="animation",
            model_profile_id=profile.id,
            runtime="fake",
        )

        script = [
            write("animation/scenes/s-hook.py", _SCENE_CODES["s-hook"]),
            write("animation/scenes/s-explain.py", _SCENE_CODES["s-explain"]),
            call_tool("validate_scenes"),
            call_tool("render_preview", {"scene_id": "s-explain"}),
        ]
        api_env.app.state.runtime_factory.register("fake", lambda: FakeRuntime(script))

        turn_id = await api_env.app.state.turn_runner.start_turn(
            session.id, UserInput(text="写两个镜头并自检")
        )
        await api_env.app.state.turn_runner.wait(turn_id)

        turn = get_turn(engine, turn_id)
        assert turn is not None
        assert turn.status == "done", turn.error

        events = list_events(engine, session.id)
        tool_call_names = {
            e.payload["call_id"]: e.payload["name"] for e in events if e.type == "tool_call"
        }
        tool_results_by_name = {
            tool_call_names[e.payload["call_id"]]: e.payload
            for e in events
            if e.type == "tool_result"
        }

        validate_result = tool_results_by_name["validate_scenes"]
        assert validate_result["is_error"] is False
        assert "全部 2 个镜头静态校验通过" in validate_result["text"]

        preview_result = tool_results_by_name["render_preview"]
        assert preview_result["is_error"] is False
        assert "s-explain" in preview_result["text"]
        assert len(preview_result["images"]) == 2  # s-explain 有 2 个 beat（T4 fixture）

        # ------------------------------------------------------------------
        # 2. 创建 final_render 任务（T10），worker 跑一次（T5）产出成片。
        # ------------------------------------------------------------------
        create_response = await api_env.client.post(f"/api/projects/{pid}/render")
        assert create_response.status_code == 201, create_response.text
        job_id = create_response.json()["id"]

        claimed = await run_once(engine, api_env.app.state.blobs, data_dir=api_env.data_dir)
        assert claimed is True

        job_response = await api_env.client.get(f"/api/projects/{pid}/jobs/{job_id}")
        assert job_response.status_code == 200
        job_body = job_response.json()
        assert job_body["status"] == "done", job_body.get("error")

        final_video = api_env.workdir(pid) / "output" / "final.mp4"
        final_meta = api_env.workdir(pid) / "output" / "final.json"
        assert final_video.is_file() and final_video.stat().st_size > 0
        assert final_meta.is_file()

        download_response = await api_env.client.get(f"/api/projects/{pid}/output/final.mp4")
        assert download_response.status_code == 200
        assert download_response.headers["content-type"] == "video/mp4"

        # ------------------------------------------------------------------
        # 3. 成片定稿（T11）：阶段变 finalized，项目标记完成。
        # ------------------------------------------------------------------
        finalize_response = await api_env.client.post(
            f"/api/projects/{pid}/animation/finalize-render"
        )
        assert finalize_response.status_code == 200, finalize_response.text
        finalize_body = finalize_response.json()
        assert finalize_body["status"] == "finalized"
        assert finalize_body["finalized_snapshot_id"]

        project_response = await api_env.client.get(f"/api/projects/{pid}")
        assert project_response.status_code == 200
        assert project_response.json()["completed_at"] is not None
