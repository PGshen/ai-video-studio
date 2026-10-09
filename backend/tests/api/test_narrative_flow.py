"""端到端集成测试（M3 T8）：叙事产物真的能喂给动画阶段（AC6）。

不重新测试单个工具的正确性（T3/T5/T6 已覆盖）。这条测试只验证把它们串起来
没问题：

选题定稿（T4 fixture）→ narrative agent（真实 `TurnRunner` + `FakeRuntime`）
跑一轮：写 `narrative.json` → `validate_narrative` → `synthesize_tts`（假 TTS
引擎，不发网络请求）→ `stage_flow.finalize` 定稿叙事，动画阶段解锁 → 动画阶段
开一轮，`upstream/narrative/` 里能读到同 schema 的产物，`validate_scenes_html` 能
解析出镜头 id（此时还没写镜头脚本，所以它会点名缺脚本的镜头，这正好证明 id 列表
读得懂）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fixtures.narrative.seed import seed_narrative_project
from studio.agent import stage_flow
from studio.agent.fake import FakeRuntime, call_tool, write
from studio.agent.runtime import UserInput
from studio.db.repo.profiles import get_model_profile
from studio.db.repo.sessions import create_session
from studio.db.repo.stages import get_stage
from studio.db.repo.turns import get_turn, list_events
from studio.engines.tts.base import TTSRequest, TTSResult, WordTimestamp
from studio.stages.narrative import synthesize_tts as synthesize_tts_module

from .conftest import ApiEnv

_ANIMATION_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "animation"
_SECONDS_PER_CHAR = 0.1


def _beat(cue_text: str, transition: str) -> dict[str, str]:
    return {
        "cue_text": cue_text,
        "visual_action": "画面动作",
        "emphasis": "要点",
        "transition": transition,
    }


# 结构与 M2 的 animation fixture 一致（同样的镜头 id 和 beat 数），但 cue_text 带着标点
# 拼回旁白——新 schema 只归一全半角标点、去空白，不会丢标点（M2 fixture 的 cue_text
# 没有标点，过不了 `validate_narrative`）。
_NARRATIVE_DOC = {
    "scenes": [
        {
            "id": "s-hook",
            "narration": "如果一个排序算法能在一秒内处理十亿条记录，你会好奇它到底做了什么。",
            "visual_intent": "用不断增长的数字条引出问题。",
            "beats": [
                _beat("如果一个排序算法能在一秒内处理十亿条记录，", "reveal"),
                _beat("你会好奇它到底做了什么。", "continue"),
            ],
        },
        {
            "id": "s-explain",
            "narration": "答案是分而治之：把大问题拆成小问题，分别解决后再合并。",
            "visual_intent": "用分裂再合并的动画展示分治。",
            "beats": [
                _beat("答案是分而治之：把大问题拆成小问题，", "transform"),
                _beat("分别解决后再合并。", "exit"),
            ],
        },
    ]
}


class _CharTimestampTTSEngine:
    """每个字 0.1 秒、逐字给时间戳的测试替身。"""

    engine_name = "fake"

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        timestamps = [
            WordTimestamp(
                word=char,
                start_time=round(index * _SECONDS_PER_CHAR, 3),
                end_time=round((index + 1) * _SECONDS_PER_CHAR, 3),
            )
            for index, char in enumerate(request.text)
        ]
        return TTSResult(
            success=True,
            output_path=None,
            duration_seconds=round(len(request.text) * _SECONDS_PER_CHAR, 3),
            error_message=None,
            audio_bytes=f"AUDIO:{request.text}".encode(),
            word_timestamps=timestamps,
        )

    async def health_check(self) -> bool:
        return True


def _stage_status(api_env: ApiEnv, project_id: str, stage: str) -> str:
    row = get_stage(api_env.app.state.engine, project_id, stage)
    assert row is not None
    return row.status


def _tool_results_by_name(api_env: ApiEnv, session_id: str) -> dict[str, dict]:
    events = list_events(api_env.app.state.engine, session_id)
    names = {e.payload["call_id"]: e.payload["name"] for e in events if e.type == "tool_call"}
    return {names[e.payload["call_id"]]: e.payload for e in events if e.type == "tool_result"}


async def _run_turn(api_env: ApiEnv, project_id: str, stage: str, script: list) -> str:
    engine = api_env.app.state.engine
    profile = get_model_profile(engine, "fake")
    assert profile is not None
    session = create_session(
        engine,
        project_id=project_id,
        stage=stage,
        model_profile_id=profile.id,
        runtime="fake",
    )
    api_env.app.state.runtime_factory.register("fake", lambda: FakeRuntime(script))
    turn_id = await api_env.app.state.turn_runner.start_turn(session.id, UserInput(text="开始"))
    await api_env.app.state.turn_runner.wait(turn_id)
    turn = get_turn(engine, turn_id)
    assert turn is not None
    assert turn.status == "done", turn.error
    return session.id


class TestNarrativeEndToEndFlow:
    async def test_narrative_turn_finalize_and_animation_reads_it(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(synthesize_tts_module, "_ENGINE_FACTORY", _CharTimestampTTSEngine)
        engine = api_env.app.state.engine
        blobs = api_env.app.state.blobs
        pid = seed_narrative_project(engine, blobs, data_dir=api_env.data_dir)
        narrative_text = json.dumps(_NARRATIVE_DOC, ensure_ascii=False)

        # 1. narrative agent 跑一轮：写产物 → 校验 → 配音。
        session_id = await _run_turn(
            api_env,
            pid,
            "narrative",
            [
                write("narrative/narrative.json", narrative_text),
                call_tool("validate_narrative"),
                call_tool("synthesize_tts"),
            ],
        )
        results = _tool_results_by_name(api_env, session_id)
        assert results["validate_narrative"]["is_error"] is False, results["validate_narrative"]
        assert results["synthesize_tts"]["is_error"] is False, results["synthesize_tts"]["text"]

        workdir = api_env.workdir(pid)
        timing = json.loads((workdir / "narrative" / "timing.json").read_text(encoding="utf-8"))
        fixture_timing = json.loads(
            (_ANIMATION_FIXTURE_DIR / "timing.json").read_text(encoding="utf-8")
        )
        assert [s["id"] for s in timing["scenes"]] == ["s-hook", "s-explain"]
        for scene, fixture_scene in zip(timing["scenes"], fixture_timing["scenes"], strict=True):
            # 动画阶段读取的字段与 M2 fixture 一致；多出来的只有 TD-36 的配音输入记录。
            assert set(scene) - set(fixture_scene) == {"narration", "voice", "speed"}
            assert set(fixture_scene) <= set(scene)
            assert set(scene["beats"][0]) == set(fixture_scene["beats"][0])
            assert set(scene["word_timestamps"][0]) == set(fixture_scene["word_timestamps"][0])
            assert (workdir / scene["audio_path"]).is_file()
            assert scene["alignment_coverage"] == 1.0

        # 2. 叙事定稿：动画阶段从 locked 变 active。
        assert _stage_status(api_env, pid, "animation_html") == "locked"
        stage_flow.finalize(engine, blobs, api_env.app.state.registry, pid, "narrative")
        assert _stage_status(api_env, pid, "animation_html") == "active"

        # 3. 动画阶段开一轮：upstream/narrative/ 有同 schema 的产物，validate_scenes_html
        #    读得懂镜头 id（还没写镜头脚本，所以点名缺脚本的镜头）。
        animation_session_id = await _run_turn(
            api_env, pid, "animation_html", [call_tool("validate_scenes_html")]
        )
        upstream_dir = workdir / "upstream" / "narrative"
        assert json.loads((upstream_dir / "narrative.json").read_text(encoding="utf-8")) == (
            json.loads(narrative_text)
        )
        assert (upstream_dir / "timing.json").is_file()

        validate_result = _tool_results_by_name(api_env, animation_session_id)[
            "validate_scenes_html"
        ]
        assert validate_result["is_error"] is True
        assert "s-hook" in validate_result["text"]
        assert "s-explain" in validate_result["text"]
