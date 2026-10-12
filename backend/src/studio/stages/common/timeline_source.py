"""工具从哪里取时间轴（free-mode 设计 §5.1）。

- `upstream`：读 `upstream/`（讲解的 `music`、`animation_html`：上游定稿后由 `prepare_turn` 派生）。
- `live_silent`：无旁白，即时从 `animation/shots.json` 与 `music/` 构建
  （`produce`、`free_produce`）。
- `live_narrated`：有旁白但没有上游，即时从工作区**顶层** `narrative/` 构建；有 `music/events.json`
  时可叠加配乐层（`free_explainer`）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from studio.timeline.load import LoadedTimeline, TimelineSources, load_timeline

TimelineSourceKind = Literal["upstream", "live_silent", "live_narrated"]

_SOURCES: dict[str, TimelineSourceKind] = {
    "produce": "live_silent",
    "free_produce": "live_silent",
    "free_explainer": "live_narrated",
}


def timeline_source(stage: str) -> TimelineSourceKind:
    return _SOURCES.get(stage, "upstream")


def load_live_narrated(workdir: Path, *, with_music: bool) -> LoadedTimeline:
    """自由讲解的时间轴：顶层旁白，配乐层只在 `music/events.json` 存在且 `with_music` 时叠加。

    `with_music=False` 是配乐脚本的输入，其 `base_hash` 写进 `music/render.json`，与成片前置检查
    （worker 按项目类型读顶层文件）口径一致。
    """
    music_source = "synth" if (workdir / "music" / "events.json").is_file() else "none"
    return load_timeline(
        TimelineSources(workdir, narration=True, music_source=music_source, with_music=with_music)
    )
