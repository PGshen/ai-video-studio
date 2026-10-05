"""Fakes shared by the HTML worker tests: a backend that writes a few bytes instead of rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio.engines.render.base import (
    PreviewRequest,
    PreviewResult,
    RenderRequest,
    RenderResult,
    SceneInput,
)
from studio.engines.render.html.assemble import AssembledPage
from studio.engines.render.mix import AudioTrack, MusicMix
from studio.worker_html import HtmlBackend


@dataclass
class FakeBackend:
    video_calls: list[dict[str, Any]] = field(default_factory=list)
    mix_calls: list[dict[str, Any]] = field(default_factory=list)
    video_error: Exception | None = None
    mix_error: Exception | None = None
    on_video: Any = None

    async def render_video(
        self, page: AssembledPage, duration: float, output: Path, fps: int, on_progress: Any
    ) -> None:
        self.video_calls.append({"page": page, "duration": duration, "fps": fps})
        if self.on_video is not None:
            await self.on_video(on_progress)
        if self.video_error is not None:
            raise self.video_error
        output.parent.mkdir(parents=True, exist_ok=True)  # like render_silent_video
        output.write_bytes(b"silent-video")

    async def mix(
        self,
        video: Path,
        tracks: list[AudioTrack],
        duration: float,
        output: Path,
        music: MusicMix | None = None,
    ) -> None:
        self.mix_calls.append(
            {"video": video, "tracks": tracks, "duration": duration, "music": music}
        )
        if self.mix_error is not None:
            raise self.mix_error
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"final-video:" + video.read_bytes())

    def as_backend(self) -> HtmlBackend:
        return HtmlBackend(render_video=self.render_video, mix=self.mix)


class ExplodingManim:
    """HTML 项目绝不能碰 Manim 引擎。"""

    engine_name = "exploding"

    async def validate_code(self, scenes: list[SceneInput]) -> tuple[bool, str]:
        raise AssertionError("manim engine used for an html project")

    async def render_preview(self, request: PreviewRequest) -> PreviewResult:
        raise AssertionError("manim engine used for an html project")

    async def health_check(self) -> bool:
        raise AssertionError("manim engine used for an html project")

    async def render(self, request: RenderRequest, work_dir: str | None = None) -> RenderResult:
        raise AssertionError("manim engine used for an html project")
