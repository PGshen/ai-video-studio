"""新项目的默认音色与语速。

音色本身（别名、speaker id、豆包版本）已迁到 `tts_voices` 表（`db.repo.voices`），在设置页
增删；迁移 0012 写入原来的 6 个音色。
"""

from __future__ import annotations

DEFAULT_VOICE = "zizi"
DEFAULT_SPEED = 1.0
