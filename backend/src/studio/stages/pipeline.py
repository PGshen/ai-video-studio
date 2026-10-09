"""Project kind and pipeline derivation (stdlib only).

A project's kind is a (engine, narration, music_source) triple; the video kind
and the ordered stage list are derived from it, never stored independently.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

Engine = Literal["manim", "html"]
MusicSource = Literal["none", "synth", "import"]
VideoKind = Literal["explainer_manim", "explainer_html", "motion_reel", "music_video"]

KIND_SETTING_KEYS: tuple[str, ...] = (
    "video_kind",
    "engine",
    "narration",
    "music_source",
    "pipeline",
)


@dataclass(frozen=True)
class ProjectKind:
    engine: Engine
    narration: bool
    music_source: MusicSource


# Projects created before kinds existed carry no kind fields in settings.
# Manim is retired (ADR 0027): such projects stay readable but can no longer be created.
LEGACY_KIND = ProjectKind(engine="manim", narration=True, music_source="none")

# Kind for creation requests that give no kind fields.
DEFAULT_KIND = ProjectKind(engine="html", narration=True, music_source="none")


def kind_errors(kind: ProjectKind) -> list[str]:
    errors: list[str] = []
    if not kind.narration and kind.music_source == "none":
        errors.append("无旁白的项目必须配乐（music_source 不能为 none）")
    if not kind.narration and kind.engine != "html":
        errors.append("无旁白的项目只支持 HTML 引擎（engine 必须为 html）")
    return errors


def video_kind_of(kind: ProjectKind) -> VideoKind:
    if kind.narration:
        return "explainer_html" if kind.engine == "html" else "explainer_manim"
    return "music_video" if kind.music_source == "import" else "motion_reel"


def build_pipeline(kind: ProjectKind) -> list[str]:
    errors = kind_errors(kind)
    if errors:
        raise ValueError("；".join(errors))
    video_kind = video_kind_of(kind)
    if video_kind in ("motion_reel", "music_video"):
        return ["concept", "produce"]
    stages = ["topic", "narrative"]
    if kind.music_source != "none":
        stages.append("music")
    stages.append("animation_html" if kind.engine == "html" else "animation")
    return stages


def valid_kinds() -> list[ProjectKind]:
    """Creatable kinds; the retired Manim engine is not among them."""
    sources: tuple[MusicSource, ...] = ("none", "synth", "import")
    kinds = [ProjectKind("html", True, source) for source in sources]
    kinds.append(ProjectKind("html", False, "synth"))
    kinds.append(ProjectKind("html", False, "import"))
    return kinds


@dataclass(frozen=True)
class Preset:
    video_kind: VideoKind
    label: str
    description: str
    music_choices: tuple[MusicSource, ...]
    default: ProjectKind


PRESETS: tuple[Preset, ...] = (
    Preset(
        video_kind="explainer_html",
        label="知识讲解（HTML）",
        description="有旁白的知识讲解视频，用 HTML 页面动画呈现，版式更灵活。",
        music_choices=("none", "synth", "import"),
        default=ProjectKind("html", True, "none"),
    ),
    Preset(
        video_kind="motion_reel",
        label="动态图形短片",
        description="无旁白的动态图形短片，先定创意与要求，再由模型一并完成配乐与动画。",
        music_choices=("synth",),
        default=ProjectKind("html", False, "synth"),
    ),
    Preset(
        video_kind="music_video",
        label="音乐 MV",
        description="无旁白的音乐 MV，先基于上传的歌曲定创意与要求，再由模型完成画面。",
        music_choices=("import",),
        default=ProjectKind("html", False, "import"),
    ),
)


def kind_from_settings(settings: Mapping[str, Any]) -> ProjectKind:
    """Legacy kind when fields are missing or hold values outside their allowed set."""
    engine = settings.get("engine")
    narration = settings.get("narration")
    music_source = settings.get("music_source")
    if (
        engine not in ("manim", "html")
        or not isinstance(narration, bool)
        or music_source not in ("none", "synth", "import")
    ):
        return LEGACY_KIND
    return ProjectKind(
        engine=cast(Engine, engine),
        narration=narration,
        music_source=cast(MusicSource, music_source),
    )


def kind_settings(kind: ProjectKind) -> dict[str, Any]:
    return {
        "video_kind": video_kind_of(kind),
        "engine": kind.engine,
        "narration": kind.narration,
        "music_source": kind.music_source,
        "pipeline": build_pipeline(kind),
    }
