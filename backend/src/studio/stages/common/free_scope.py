"""两个自由阶段（`free_explainer`、`free_produce`）共用的可写范围（free-mode 设计 §4.3）。

整个工作区可写（`fnmatch` 的 `*` 匹配 `/`）；工具生成的文件、用户上传的歌曲与歌词、项目风格
`style/` 以及系统目录（`upstream/`、`output/`、`.cache/`）列进 `tool_managed`：
`WriteScope` 没有排除列表，借越界防线把它们还原为本轮开始时的内容
（没有工具会写 `style/`，所以它实际上是只读的）。`uploads/` 由 `is_writable` 统一禁止。
"""

from __future__ import annotations

from collections.abc import Sequence

from studio.stages.common.music_source import SOURCE_EXTENSIONS
from studio.workspace.scope import WriteScope

_MUSIC_OUTPUTS = (
    "music/music.wav",
    "music/events.json",
    "music/analysis.json",
    "music/analysis.png",
    "music/render.json",
)


def free_write_scope(extra_tool_managed: Sequence[str] = ()) -> WriteScope:
    return WriteScope(
        writable=["*"],
        tool_managed=[
            *_MUSIC_OUTPUTS,
            *(f"music/source.{ext}" for ext in SOURCE_EXTENSIONS),  # written by the upload endpoint
            "music/lyrics.lrc",  # written by the upload endpoint
            "style/*",
            # System dirs: derived copies, worker output, caches (never agent-written).
            "upstream/*",
            "output/*",
            ".cache/*",
            *extra_tool_managed,
        ],
    )
