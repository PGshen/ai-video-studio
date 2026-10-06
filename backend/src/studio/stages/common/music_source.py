"""用户上传的歌曲 `music/source.<ext>`：判断项目是否为歌曲形态（音乐 MV）的唯一信号。

`produce`、`concept` 与各工具用同一规则：工作区里有源文件就是 MV，没有就是（合成配乐的）短片。
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
