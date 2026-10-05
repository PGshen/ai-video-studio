"""`GET /api/video-kinds`（pipeline-config T5）。"""

from __future__ import annotations

from .conftest import ApiEnv, register_reel_stages


async def test_default_registry_only_the_two_explainers_available(api_env: ApiEnv) -> None:
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
        ("html", True, "none"),
    ]
    assert available[0]["pipeline"] == ["topic", "narrative", "animation"]
    assert available[1]["pipeline"] == ["topic", "narrative", "animation_html"]
    assert all(k["unavailable_reason"] is None for k in available)
    for kind in kinds:
        if not kind["available"]:
            assert "阶段尚未实现" in kind["unavailable_reason"]


async def test_unavailable_reason_lists_missing_stages_in_pipeline_order(api_env: ApiEnv) -> None:
    body = (await api_env.client.get("/api/video-kinds")).json()

    reel = next(k for k in body["kinds"] if k["video_kind"] == "motion_reel")
    assert reel["unavailable_reason"] == "「配乐」阶段尚未实现"  # concept, beatsheet are registered
    synth = next(
        k
        for k in body["kinds"]
        if (k["engine"], k["narration"], k["music_source"]) == ("manim", True, "synth")
    )
    assert synth["unavailable_reason"] == "「配乐」阶段尚未实现"


async def test_kinds_become_available_when_stages_registered(api_env: ApiEnv) -> None:
    register_reel_stages(api_env.app.state.registry)

    body = (await api_env.client.get("/api/video-kinds")).json()

    by_kind = {(k["engine"], k["narration"], k["music_source"]): k for k in body["kinds"]}
    assert by_kind[("html", False, "import")]["available"] is True
    assert by_kind[("manim", True, "synth")]["available"] is True
    assert by_kind[("html", True, "none")]["available"] is True
