"""完全自由阶段（`open`）的可写范围（open-mode 设计 §4.1）。

整个工作区可写，`style/`、`project.md` 也可以改；只有系统目录列进 `tool_managed`（借越界防线
还原）。`uploads/` 由 `is_writable` 统一禁止。放在 `stages.common` 是因为 `open` 阶段和它的
`tts` 工具都要用，而各阶段之间、`common` 到具体阶段都不能互相 import。
"""

from __future__ import annotations

from studio.workspace.scope import WriteScope

OPEN_WRITE_SCOPE = WriteScope(
    writable=["*"],
    tool_managed=["upstream/*", "output/*", ".cache/*"],
)
