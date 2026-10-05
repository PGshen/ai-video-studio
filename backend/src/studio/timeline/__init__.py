"""统一时间轴（子项目 2 设计 §4）：纯能力层，只依赖标准库和 pydantic。"""

from studio.timeline.build import (
    GridInput,
    LayerNotSupported,
    MomentInput,
    MusicInput,
    NarrationInput,
    SectionInput,
    TimelineError,
    TimelineLayers,
    build_timeline,
    narration_from_documents,
    timeline_hash,
)
from studio.timeline.notation import parse_at
from studio.timeline.schema import (
    Beat,
    Energy,
    Grid,
    Moment,
    Music,
    MusicEvent,
    NarrationScene,
    Section,
    Timeline,
)

__all__ = [
    "Beat",
    "Energy",
    "Grid",
    "GridInput",
    "LayerNotSupported",
    "Moment",
    "MomentInput",
    "Music",
    "MusicEvent",
    "MusicInput",
    "NarrationInput",
    "NarrationScene",
    "Section",
    "SectionInput",
    "Timeline",
    "TimelineError",
    "TimelineLayers",
    "build_timeline",
    "narration_from_documents",
    "parse_at",
    "timeline_hash",
]
