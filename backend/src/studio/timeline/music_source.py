"""用户上传的歌曲 `music/source.<ext>` 的唯一查找规则（TD-76）。

放在 `timeline`（纯能力层）里，因为时间轴读取也要用它，而 `timeline` 不能 import `stages`；
`studio.stages.common.music_source` 重新导出，阶段、api 和工具照旧从那里取。
"""

from __future__ import annotations

from pathlib import Path

SOURCE_EXTENSIONS = ("mp3", "wav", "m4a", "flac", "ogg")
"""导入形态的源文件扩展名白名单（与上传端点一致）；也是 `find_sources` 的排序。"""


def find_sources(music_dir: Path) -> list[Path]:
    """`music_dir` 下所有白名单扩展名的 `source.<ext>`，按扩展名顺序。

    只认普通文件：目录和符号链接都不算（上传端点只会写普通文件，符号链接可能指向工作区之外）。
    目录不存在时返回空列表。"""
    found: list[Path] = []
    for ext in SOURCE_EXTENSIONS:
        path = music_dir / f"source.{ext}"
        if not path.is_symlink() and path.is_file():
            found.append(path)
    return found


def find_source(music_dir: Path) -> Path | None:
    """`find_sources` 的第一个；没有返回 `None`。"""
    sources = find_sources(music_dir)
    return sources[0] if sources else None
