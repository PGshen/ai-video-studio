"""画面（HTML / Canvas 2D）的共用工具与参考：`validate_scenes_html`、`render_preview_html`、金样本。

`animation_html`（讲解）与 `produce`（短片、MV）两个阶段共用，逻辑只写一份（规则 3）。
"""

from pathlib import Path

CANVAS_EXEMPLAR = Path(__file__).parent / "exemplar" / "canvas-techniques.js"
"""系统自带的画面技法金样本；阶段的 `prepare_turn` 把它复制到 `upstream/exemplar/`。"""

LYRICS_EXEMPLAR = Path(__file__).parent / "exemplar" / "lyrics-techniques.js"
"""歌词驱动的画面金样本（字幕条、关键字、数字滚轮、曲线、打字、整屏大字）；只在项目有歌词时复制。"""
