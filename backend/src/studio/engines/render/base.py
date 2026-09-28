"""渲染引擎的协议与共享数据类型。

从 `../ai-video/backend/app/engines/render/base.py` 迁移，仅改了 import 路径；
新增 `PreviewRequest`/`PreviewResult`/`PreviewKeyframe`（T2 用）和
`RenderEngine.render_preview` 方法签名，本任务（T1）只声明，T2 实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SceneAudio:
    scene_index: int
    audio_path: str
    duration_seconds: float


@dataclass
class SceneInput:
    scene_index: int
    narration: str
    description: str
    code: str
    audio: SceneAudio | None


@dataclass
class RenderRequest:
    scenes: list[SceneInput]
    output_format: str
    resolution: tuple[int, int]
    fps: int = 30


@dataclass
class RenderResult:
    success: bool
    output_path: str | None
    duration_seconds: float | None
    error_message: str | None
    render_log: str


class RenderResultWithBytes(RenderResult):
    def __init__(self, *args, video_bytes: bytes, **kwargs):
        super().__init__(*args, **kwargs)
        self.video_bytes = video_bytes


@dataclass
class PreviewKeyframe:
    beat_index: int
    png_bytes: bytes


@dataclass
class PreviewRequest:
    scenes: list[SceneInput]
    """0..scene_index（含），沿用全画质渲染的合并脚本方式。"""
    target_scene_index: int
    beat_end_times: list[float]
    """目标镜头内各 beat 结束时刻，相对该镜头起点。"""
    audio_duration_seconds: float | None


@dataclass
class PreviewResult:
    success: bool
    error_message: str | None
    render_duration_seconds: float | None
    duration_deviation_seconds: float | None
    keyframes: list[PreviewKeyframe]
    render_log: str


class RenderEngine(Protocol):
    @property
    def engine_name(self) -> str: ...

    async def validate_code(self, scenes: list[SceneInput]) -> tuple[bool, str]: ...

    async def render(self, request: RenderRequest) -> RenderResult: ...

    async def render_preview(self, request: PreviewRequest) -> PreviewResult: ...

    async def health_check(self) -> bool: ...


class EngineRegistry[T: RenderEngine]:
    def __init__(self):
        self._engines: dict[str, T] = {}

    def register(self, engine: T) -> None:
        self._engines[engine.engine_name] = engine

    def get(self, name: str) -> T:
        if name not in self._engines:
            raise ValueError(f"Unknown engine: {name}")
        return self._engines[name]

    def list_engines(self) -> list[str]:
        return list(self._engines.keys())
