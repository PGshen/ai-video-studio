"""配乐的共用工具与参考：`render_music`、`analyze_music`、事件校验与金样本。

`music`（讲解 + 背景乐）与 `produce`（短片、MV）两个阶段共用，逻辑只写一份（规则 3）。
"""

from pathlib import Path

AUDIO_EXEMPLAR = Path(__file__).parent / "exemplar" / "audio-techniques.py"
"""系统自带的合成技法金样本；阶段的 `prepare_turn` 把它复制到 `upstream/exemplar/`。"""
