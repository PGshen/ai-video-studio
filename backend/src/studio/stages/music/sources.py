"""`music` 阶段按工作区内容推断时间轴来源（阶段和工具拿不到项目设置）。

有 `beatsheet/beatsheet.json` 的是短片（无旁白），否则是有旁白的讲解 + 背景乐。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from studio.stages.common.music_source import SOURCE_EXTENSIONS, find_source
from studio.timeline.load import TimelineSources

__all__ = ["SOURCE_EXTENSIONS", "import_source", "infer_sources", "section_energy"]

_BEATSHEET = "beatsheet/beatsheet.json"


def import_source(workdir: Path) -> Path | None:
    """工作区里的 `music/source.<ext>`（导入形态的标志）；没有返回 `None`。"""
    return find_source(workdir / "music")


def infer_sources(workdir: Path, prefix: str, *, with_music: bool) -> TimelineSources:
    narration = not (workdir / prefix / _BEATSHEET).is_file()
    return TimelineSources(
        root=workdir,
        narration=narration,
        music_source="synth",
        prefix=prefix,
        with_music=with_music,
    )


def section_energy(beatsheet: Mapping[str, Any] | None) -> dict[str, str]:
    """段落 id → 节拍脚本里声明的能量档位；讲解（没有节拍脚本）为空。"""
    sections = (beatsheet or {}).get("sections", [])
    return {
        section["id"]: section["energy"]
        for section in sections
        if isinstance(section, dict) and isinstance(section.get("energy"), str)
    }
