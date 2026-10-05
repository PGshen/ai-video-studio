"""`music` 阶段按工作区内容推断时间轴来源（阶段和工具拿不到项目设置）。

有 `beatsheet/beatsheet.json` 的是短片（无旁白），否则是有旁白的讲解 + 背景乐。
"""

from __future__ import annotations

from pathlib import Path

from studio.timeline.load import TimelineSources

_BEATSHEET = "beatsheet/beatsheet.json"


def infer_sources(workdir: Path, prefix: str, *, with_music: bool) -> TimelineSources:
    narration = not (workdir / prefix / _BEATSHEET).is_file()
    return TimelineSources(
        root=workdir,
        narration=narration,
        music_source="synth",
        prefix=prefix,
        with_music=with_music,
    )
