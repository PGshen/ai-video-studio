"""导入音乐的源文件 `music/source.<ext>`：判断项目是否为导入形态（音乐 MV）的唯一信号。

`music` 阶段用它分流两种形态，`animation_html` 用同一规则读上游 `upstream/music/`；
只有 `sections.json` 而没有源文件（例如合成形态留下的文件）不算导入形态。
"""

from __future__ import annotations

from pathlib import Path

SOURCE_EXTENSIONS = ("mp3", "wav", "m4a", "flac", "ogg")
"""导入形态的源文件扩展名白名单（与上传端点一致）。"""


def find_source(music_dir: Path) -> Path | None:
    """`music_dir` 下第一个白名单扩展名的 `source.<ext>`；没有返回 `None`。"""
    for ext in SOURCE_EXTENSIONS:
        path = music_dir / f"source.{ext}"
        if path.is_file():
            return path
    return None
