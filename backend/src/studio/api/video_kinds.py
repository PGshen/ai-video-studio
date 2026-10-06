"""`GET /api/video-kinds`：可创建的视频类型（预设 + 8 种合法配置及其可用性）。

可用性 = 流水线里的每个阶段都已在注册表里注册；尚未实现的阶段会让对应类型显示为不可用，
并给出可读原因。导入音乐只有无旁白的 HTML 音乐视频这一种形态（时间轴读取不支持旁白）。
项目创建端点复用同一个判断（`unavailable_reason`）。
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter, Depends

from studio.agent.stage import StageRegistry
from studio.api.deps import get_registry
from studio.api.schemas import (
    KindOptionOut,
    PresetOut,
    ProjectKindConfig,
    VideoKindsOut,
)
from studio.stages.pipeline import PRESETS, build_pipeline, valid_kinds, video_kind_of

router = APIRouter(prefix="/api", tags=["video-kinds"])

# Keep in sync with the frontend `STAGE_TITLES`.
STAGE_TITLES: dict[str, str] = {
    "topic": "选题",
    "concept": "创意与要求",
    "narrative": "叙事",
    "music": "配乐",
    "produce": "配乐与动画",
    "animation": "动画",
    "animation_html": "动画",
}


def unavailable_reason(
    pipeline: Sequence[str],
    registry: StageRegistry,
    music_source: str | None = None,
    engine: str | None = None,
    narration: bool | None = None,
) -> str | None:
    """流水线里有未注册阶段时返回中文原因（按流水线顺序列出全部）；导入音乐只支持无旁白的 HTML
    音乐视频（`engine`/`narration` 给出时才判断）；Manim 动画阶段不读配乐、成片也不混音，所以
    Manim 加配乐不可用。可用返回 `None`。"""
    missing = [name for name in pipeline if not registry.has(name)]
    if missing:
        titles = "".join(f"「{STAGE_TITLES.get(name, name)}」" for name in missing)
        return f"{titles}阶段尚未实现"
    if music_source == "import" and (engine == "manim" or narration is True):
        return "「配乐（导入音乐）」目前只支持无旁白的 HTML 音乐视频"
    if engine == "manim" and music_source not in (None, "none"):
        return "「配乐」暂不支持 Manim 动画（成片不会混入配乐）"
    return None


@router.get("/video-kinds", response_model=VideoKindsOut)
def list_video_kinds_endpoint(registry: StageRegistry = Depends(get_registry)) -> VideoKindsOut:
    presets = [
        PresetOut(
            video_kind=preset.video_kind,
            label=preset.label,
            description=preset.description,
            music_choices=list(preset.music_choices),
            default=ProjectKindConfig(
                engine=preset.default.engine,
                narration=preset.default.narration,
                music_source=preset.default.music_source,
            ),
        )
        for preset in PRESETS
    ]
    kinds: list[KindOptionOut] = []
    for kind in valid_kinds():
        pipeline = build_pipeline(kind)
        reason = unavailable_reason(
            pipeline, registry, kind.music_source, kind.engine, kind.narration
        )
        kinds.append(
            KindOptionOut(
                engine=kind.engine,
                narration=kind.narration,
                music_source=kind.music_source,
                video_kind=video_kind_of(kind),
                pipeline=pipeline,
                available=reason is None,
                unavailable_reason=reason,
            )
        )
    return VideoKindsOut(presets=presets, kinds=kinds)
