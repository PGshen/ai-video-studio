"""Project kind and pipeline derivation (stdlib only).

A project's kind is an (engine, narration, music_source, mode) tuple; the video kind
and the ordered stage list are derived from it, never stored independently.
`mode="free"` projects have a single stage that does everything (free-mode design).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

Engine = Literal["manim", "html"]
MusicSource = Literal["none", "synth", "import"]
VideoKind = Literal["explainer_manim", "explainer_html", "motion_reel", "music_video"]
Mode = Literal["staged", "free"]

FREE_EXPLAINER_STAGE = "free_explainer"
FREE_PRODUCE_STAGE = "free_produce"
FREE_STAGES: tuple[str, ...] = (FREE_EXPLAINER_STAGE, FREE_PRODUCE_STAGE)

KIND_SETTING_KEYS: tuple[str, ...] = (
    "video_kind",
    "engine",
    "narration",
    "music_source",
    "mode",
    "pipeline",
)


@dataclass(frozen=True)
class ProjectKind:
    engine: Engine
    narration: bool
    music_source: MusicSource
    mode: Mode = "staged"


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
    if kind.mode == "free" and kind.narration and kind.music_source == "import":
        errors.append("自由讲解不支持导入音乐（music_source 只能是 none 或 synth）")
    return errors


def video_kind_of(kind: ProjectKind) -> VideoKind:
    if kind.narration:
        return "explainer_html" if kind.engine == "html" else "explainer_manim"
    return "music_video" if kind.music_source == "import" else "motion_reel"


def build_pipeline(kind: ProjectKind) -> list[str]:
    errors = kind_errors(kind)
    if errors:
        raise ValueError("；".join(errors))
    if kind.mode == "free":
        return [FREE_EXPLAINER_STAGE if kind.narration else FREE_PRODUCE_STAGE]
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
    kinds += [ProjectKind("html", True, source, "free") for source in ("none", "synth")]
    kinds.append(ProjectKind("html", False, "synth", "free"))
    kinds.append(ProjectKind("html", False, "import", "free"))
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
    Preset(
        video_kind="explainer_html",
        label="自由讲解",
        description="给一个题目直接做讲解视频：一个对话里完成写稿、配音和画面，不经过选题和阶段。",
        music_choices=("none", "synth"),
        default=ProjectKind("html", True, "none", "free"),
    ),
    Preset(
        video_kind="motion_reel",
        label="自由短片",
        description="临时做一条无旁白的主题短片：一个对话里完成配乐与动画，不经过创意阶段。",
        music_choices=("synth",),
        default=ProjectKind("html", False, "synth", "free"),
    ),
    Preset(
        video_kind="music_video",
        label="自由 MV",
        description="上传一首歌，在一个对话里直接做出 MV 画面，不经过创意阶段。",
        music_choices=("import",),
        default=ProjectKind("html", False, "import", "free"),
    ),
)


def kind_from_settings(settings: Mapping[str, Any]) -> ProjectKind:
    """Legacy kind when fields are missing or hold values outside their allowed set.

    A missing or unknown `mode` reads as `staged`: projects created before free mode carry none."""
    engine = settings.get("engine")
    narration = settings.get("narration")
    music_source = settings.get("music_source")
    if (
        engine not in ("manim", "html")
        or not isinstance(narration, bool)
        or music_source not in ("none", "synth", "import")
    ):
        return LEGACY_KIND
    mode = settings.get("mode")
    return ProjectKind(
        engine=cast(Engine, engine),
        narration=narration,
        music_source=cast(MusicSource, music_source),
        mode="free" if mode == "free" else "staged",
    )


def kind_settings(kind: ProjectKind) -> dict[str, Any]:
    return {
        "video_kind": video_kind_of(kind),
        "engine": kind.engine,
        "narration": kind.narration,
        "music_source": kind.music_source,
        "mode": kind.mode,
        "pipeline": build_pipeline(kind),
    }
