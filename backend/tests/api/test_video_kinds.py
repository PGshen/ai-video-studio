"""`GET /api/video-kinds`（pipeline-config T5）。"""

from __future__ import annotations

from .conftest import ApiEnv, register_reel_stages


async def test_default_registry_makes_the_four_presets_available(api_env: ApiEnv) -> None:
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
        ("html", True, "synth"),
        ("html", False, "synth"),
        ("html", False, "import"),
    ]
    assert available[0]["pipeline"] == ["topic", "narrative", "animation"]
    assert available[1]["pipeline"] == ["topic", "narrative", "animation_html"]
    assert available[3]["pipeline"] == ["concept", "produce"]
    assert available[4]["pipeline"] == ["concept", "produce"]
    assert all(k["unavailable_reason"] is None for k in available)
    for kind in kinds:
        if not kind["available"]:
            assert kind["unavailable_reason"].endswith(
                ("阶段尚未实现", "成片不会混入配乐）", "只支持无旁白的 HTML 音乐视频")
            )


def test_unavailable_reason_lists_missing_stages_in_pipeline_order() -> None:
    from studio.agent.stage import StageRegistry
    from studio.api.video_kinds import unavailable_reason
    from studio.stages.animation_html import STAGE as ANIMATION_HTML

    registry = StageRegistry()
    registry.register(ANIMATION_HTML)
    reel = ["concept", "produce"]

    assert unavailable_reason(reel, registry) == "「创意」「配乐与动画」阶段尚未实现"
    assert unavailable_reason(["animation_html"], registry) is None
    assert unavailable_reason(["animation_html"], registry, "import") is None
    assert unavailable_reason(["animation_html"], registry, "import", "html", False) is None
    only_mv = "「配乐（导入音乐）」目前只支持无旁白的 HTML 音乐视频"
    assert unavailable_reason(["animation_html"], registry, "import", "html", True) == only_mv
    assert unavailable_reason(["animation_html"], registry, "import", "manim", True) == only_mv
    # a missing stage is reported first
    assert unavailable_reason(reel, registry, "import", "html", False) == (
        "「创意」「配乐与动画」阶段尚未实现"
    )


async def test_real_stages_make_the_music_video_available_and_narrated_import_stays_off(
    api_env: ApiEnv,
) -> None:
    body = (await api_env.client.get("/api/video-kinds")).json()

    by_kind = {(k["engine"], k["narration"], k["music_source"]): k for k in body["kinds"]}
    for key in (("html", False, "synth"), ("html", True, "synth")):
        assert by_kind[key]["available"] is True, key
    # Manim's animation stage does not read the music, and its render path never mixes it in.
    manim_synth = by_kind[("manim", True, "synth")]
    assert manim_synth["available"] is False
    assert manim_synth["unavailable_reason"] == "「配乐」暂不支持 Manim 动画（成片不会混入配乐）"
    assert by_kind[("html", True, "none")]["available"] is True
    music_video = by_kind[("html", False, "import")]
    assert music_video["available"] is True and music_video["unavailable_reason"] is None
    # Imported music only exists as a music video: a narrated project cannot load its timeline.
    for key in (("manim", True, "import"), ("html", True, "import")):
        assert by_kind[key]["available"] is False
        assert by_kind[key]["unavailable_reason"] == (
            "「配乐（导入音乐）」目前只支持无旁白的 HTML 音乐视频"
        )


async def test_kinds_become_available_when_stages_registered(api_env: ApiEnv) -> None:
    register_reel_stages(api_env.app.state.registry)

    body = (await api_env.client.get("/api/video-kinds")).json()

    by_kind = {(k["engine"], k["narration"], k["music_source"]): k for k in body["kinds"]}
    assert by_kind[("html", False, "synth")]["available"] is True
    assert by_kind[("manim", True, "synth")]["available"] is False
    assert by_kind[("html", True, "none")]["available"] is True
