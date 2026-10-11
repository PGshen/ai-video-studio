import pytest

from studio.stages.pipeline import (
    DEFAULT_KIND,
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

# Manim is retired (ADR 0027): only stored legacy projects still derive its pipeline.
LEGACY_CASES = [
    (ProjectKind("manim", True, "none"), ["topic", "narrative", "animation"]),
    (ProjectKind("manim", True, "synth"), ["topic", "narrative", "music", "animation"]),
]

CASES = [
    (ProjectKind("html", True, "none"), ["topic", "narrative", "animation_html"]),
    (ProjectKind("html", True, "synth"), ["topic", "narrative", "music", "animation_html"]),
    (ProjectKind("html", True, "import"), ["topic", "narrative", "music", "animation_html"]),
    (ProjectKind("html", False, "synth"), ["concept", "produce"]),
    (ProjectKind("html", False, "import"), ["concept", "produce"]),
]

FREE_CASES = [
    (ProjectKind("html", True, "none", "free"), ["free_explainer"]),
    (ProjectKind("html", True, "synth", "free"), ["free_explainer"]),
    (ProjectKind("html", False, "synth", "free"), ["free_produce"]),
    (ProjectKind("html", False, "import", "free"), ["free_produce"]),
]


@pytest.mark.parametrize(("kind", "expected"), CASES + FREE_CASES + LEGACY_CASES)
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
    assert len(kinds) == 9
    assert len(set(kinds)) == 9
    assert all(k.engine == "html" for k in kinds)
    assert all(kind_errors(k) == [] for k in kinds)
    assert [k for k in kinds] == [c[0] for c in CASES + FREE_CASES]


def test_mode_defaults_to_staged() -> None:
    assert ProjectKind("html", True, "none").mode == "staged"


def test_free_narrated_kind_cannot_import_music() -> None:
    errors = kind_errors(ProjectKind("html", True, "import", "free"))
    assert len(errors) == 1
    assert "自由讲解" in errors[0]


def test_free_kind_keeps_video_kind() -> None:
    assert video_kind_of(ProjectKind("html", True, "synth", "free")) == "explainer_html"
    assert video_kind_of(ProjectKind("html", False, "synth", "free")) == "motion_reel"
    assert video_kind_of(ProjectKind("html", False, "import", "free")) == "music_video"


def test_kind_from_settings_treats_missing_or_bad_mode_as_staged() -> None:
    good = {"engine": "html", "narration": False, "music_source": "synth"}
    assert kind_from_settings(good).mode == "staged"
    assert kind_from_settings({**good, "mode": "chaos"}).mode == "staged"
    assert kind_from_settings({**good, "mode": "free"}) == ProjectKind(
        "html", False, "synth", "free"
    )


def test_kind_from_settings_legacy_and_roundtrip() -> None:
    assert kind_from_settings({}) == LEGACY_KIND
    assert LEGACY_KIND == ProjectKind("manim", True, "none")
    assert kind_from_settings(kind_settings(LEGACY_KIND)) == LEGACY_KIND
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


def test_default_kind_is_html_explainer() -> None:
    assert DEFAULT_KIND == ProjectKind("html", True, "none")


def test_presets() -> None:
    assert [(p.video_kind, p.default.mode) for p in PRESETS] == [
        ("explainer_html", "staged"),
        ("motion_reel", "staged"),
        ("music_video", "staged"),
        ("explainer_html", "free"),
        ("motion_reel", "free"),
        ("music_video", "free"),
    ]
    free_explainer = PRESETS[3]
    assert free_explainer.music_choices == ("none", "synth")
    for preset in PRESETS:
        assert kind_errors(preset.default) == []
        assert video_kind_of(preset.default) == preset.video_kind
        assert preset.default.music_source in preset.music_choices
        assert preset.label and preset.description
