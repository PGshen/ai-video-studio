import pytest

from studio.stages.pipeline import (
    KIND_SETTING_KEYS,
    LEGACY_KIND,
    PRESETS,
    ProjectKind,
    build_pipeline,
    kind_errors,
    kind_from_settings,
    kind_settings,
    valid_kinds,
    video_kind_of,
)

CASES = [
    (ProjectKind("manim", True, "none"), ["topic", "narrative", "animation"]),
    (ProjectKind("manim", True, "synth"), ["topic", "narrative", "music", "animation"]),
    (ProjectKind("manim", True, "import"), ["topic", "narrative", "music", "animation"]),
    (ProjectKind("html", True, "none"), ["topic", "narrative", "animation_html"]),
    (ProjectKind("html", True, "synth"), ["topic", "narrative", "music", "animation_html"]),
    (ProjectKind("html", True, "import"), ["topic", "narrative", "music", "animation_html"]),
    (ProjectKind("html", False, "synth"), ["concept", "beatsheet", "music", "animation_html"]),
    (ProjectKind("html", False, "import"), ["concept", "music", "beatsheet", "animation_html"]),
]


@pytest.mark.parametrize(("kind", "expected"), CASES)
def test_build_pipeline(kind: ProjectKind, expected: list[str]) -> None:
    assert build_pipeline(kind) == expected


def test_kind_errors_single_violations() -> None:
    assert len(kind_errors(ProjectKind("html", False, "none"))) == 1
    assert len(kind_errors(ProjectKind("manim", False, "synth"))) == 1


def test_kind_errors_both_violations() -> None:
    assert len(kind_errors(ProjectKind("manim", False, "none"))) == 2


def test_build_pipeline_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        build_pipeline(ProjectKind("manim", False, "none"))


def test_video_kind_of() -> None:
    assert video_kind_of(ProjectKind("manim", True, "none")) == "explainer_manim"
    assert video_kind_of(ProjectKind("html", True, "synth")) == "explainer_html"
    assert video_kind_of(ProjectKind("html", False, "synth")) == "motion_reel"
    assert video_kind_of(ProjectKind("html", False, "import")) == "music_video"


def test_valid_kinds() -> None:
    kinds = valid_kinds()
    assert len(kinds) == 8
    assert len(set(kinds)) == 8
    assert all(kind_errors(k) == [] for k in kinds)
    assert [k for k in kinds] == [c[0] for c in CASES]


def test_kind_from_settings_legacy_and_roundtrip() -> None:
    assert kind_from_settings({}) == LEGACY_KIND
    assert LEGACY_KIND == ProjectKind("manim", True, "none")
    for kind in valid_kinds():
        settings = kind_settings(kind)
        assert set(settings) == set(KIND_SETTING_KEYS)
        assert settings["pipeline"] == build_pipeline(kind)
        assert kind_from_settings(settings) == kind


def test_kind_from_settings_falls_back_to_legacy_on_bad_values() -> None:
    good = {"engine": "html", "narration": False, "music_source": "synth"}
    assert kind_from_settings(good) == ProjectKind("html", False, "synth")
    assert kind_from_settings({**good, "engine": "blender"}) == LEGACY_KIND
    assert kind_from_settings({**good, "narration": "true"}) == LEGACY_KIND
    assert kind_from_settings({**good, "music_source": "radio"}) == LEGACY_KIND


def test_kind_from_settings_falls_back_to_legacy_on_partial_fields() -> None:
    assert kind_from_settings({"engine": "html"}) == LEGACY_KIND
    assert kind_from_settings({"engine": "html", "narration": False}) == LEGACY_KIND


def test_presets() -> None:
    assert len(PRESETS) == 4
    for preset in PRESETS:
        assert kind_errors(preset.default) == []
        assert video_kind_of(preset.default) == preset.video_kind
        assert preset.default.music_source in preset.music_choices
        assert preset.label and preset.description
