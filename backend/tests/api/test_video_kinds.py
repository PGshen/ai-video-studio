"""`GET /api/video-kinds`（pipeline-config T5）。"""

from __future__ import annotations

from .conftest import ApiEnv, register_reel_stages


async def test_default_registry_everything_but_imported_music_is_available(api_env: ApiEnv) -> None:
    response = await api_env.client.get("/api/video-kinds")

    assert response.status_code == 200
    body = response.json()
    assert [p["video_kind"] for p in body["presets"]] == [
        "explainer_manim",
        "explainer_html",
        "motion_reel",
        "music_video",
    ]
    assert set(body["presets"][0]) == {
        "video_kind",
        "label",
        "description",
        "music_choices",
        "default",
    }
    assert body["presets"][0]["default"] == {
        "engine": "manim",
        "narration": True,
        "music_source": "none",
    }
    kinds = body["kinds"]
    assert len(kinds) == 8
    available = [k for k in kinds if k["available"]]
    assert [(k["engine"], k["narration"], k["music_source"]) for k in available] == [
        ("manim", True, "none"),
        ("manim", True, "synth"),
        ("html", True, "none"),
        ("html", True, "synth"),
        ("html", False, "synth"),
    ]
    assert available[0]["pipeline"] == ["topic", "narrative", "animation"]
    assert available[1]["pipeline"] == ["topic", "narrative", "music", "animation"]
    assert available[2]["pipeline"] == ["topic", "narrative", "animation_html"]
    assert available[4]["pipeline"] == ["concept", "beatsheet", "music", "animation_html"]
    assert all(k["unavailable_reason"] is None for k in available)
    for kind in kinds:
        if not kind["available"]:
            assert "阶段尚未实现" in kind["unavailable_reason"]


def test_unavailable_reason_lists_missing_stages_in_pipeline_order() -> None:
    from studio.agent.stage import StageRegistry
    from studio.api.video_kinds import unavailable_reason
    from studio.stages.animation_html import STAGE as ANIMATION_HTML

    registry = StageRegistry()
    registry.register(ANIMATION_HTML)
    reel = ["concept", "beatsheet", "music", "animation_html"]

    assert unavailable_reason(reel, registry) == "「创意」「节拍脚本」「配乐」阶段尚未实现"
    assert unavailable_reason(["animation_html"], registry) is None
    assert unavailable_reason(["animation_html"], registry, "import") == (
        "「配乐（导入音乐）」阶段尚未实现"
    )


async def test_real_stages_make_the_synth_kinds_available_and_import_stays_unavailable(
    api_env: ApiEnv,
) -> None:
    body = (await api_env.client.get("/api/video-kinds")).json()

    by_kind = {(k["engine"], k["narration"], k["music_source"]): k for k in body["kinds"]}
    for key in (("html", False, "synth"), ("manim", True, "synth"), ("html", True, "synth")):
        assert by_kind[key]["available"] is True, key
    assert by_kind[("html", True, "none")]["available"] is True
    for key in (("html", False, "import"), ("manim", True, "import"), ("html", True, "import")):
        assert by_kind[key]["available"] is False
        assert by_kind[key]["unavailable_reason"] == "「配乐（导入音乐）」阶段尚未实现"


async def test_kinds_become_available_when_stages_registered(api_env: ApiEnv) -> None:
    register_reel_stages(api_env.app.state.registry)

    body = (await api_env.client.get("/api/video-kinds")).json()

    by_kind = {(k["engine"], k["narration"], k["music_source"]): k for k in body["kinds"]}
    assert by_kind[("html", False, "synth")]["available"] is True
    assert by_kind[("manim", True, "synth")]["available"] is True
    assert by_kind[("html", True, "none")]["available"] is True
