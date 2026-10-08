"""用户上传的歌曲 `music/source.<ext>`：判断项目是否为歌曲形态（音乐 MV）的唯一信号。

`produce`、`concept` 与各工具用同一规则：工作区里有源文件就是 MV，没有就是（合成配乐的）短片。
规则本身定义在 `studio.timeline.music_source`（时间轴读取也用它，`timeline` 不能 import
`stages`），这里重新导出。
"""

from __future__ import annotations

from studio.timeline.music_source import SOURCE_EXTENSIONS, find_source, find_sources

__all__ = ["SOURCE_EXTENSIONS", "find_source", "find_sources"]
