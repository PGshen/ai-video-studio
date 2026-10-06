"""配乐工具按工作区内容判断形态（阶段和工具拿不到项目设置）。

有 `music/source.<ext>` 的是用户上传的歌曲（MV）；`music` 阶段（讲解 + 背景乐）总是有旁白，
时间轴来源固定。
"""

from __future__ import annotations

from pathlib import Path

from studio.stages.common.music_source import SOURCE_EXTENSIONS, find_source
from studio.timeline.load import TimelineSources

__all__ = ["SOURCE_EXTENSIONS", "import_source", "infer_sources"]


def import_source(workdir: Path) -> Path | None:
    """工作区里的 `music/source.<ext>`（歌曲形态的标志）；没有返回 `None`。"""
    return find_source(workdir / "music")


def infer_sources(workdir: Path, prefix: str, *, with_music: bool) -> TimelineSources:
    """讲解 + 背景乐的时间轴来源。"""
    return TimelineSources(
        root=workdir,
        narration=True,
        music_source="synth",
        prefix=prefix,
        with_music=with_music,
    )
