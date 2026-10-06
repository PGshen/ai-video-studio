"""`produce` 阶段的 `prepare_turn`：只复制两份金样本。

不再生成 `upstream/timeline.json`：镜头划分和配乐都由本阶段自己写，改一处就要立刻反映到另一处，
所以时间轴由各工具即时构建（`timeline.load` 的 `produce` 形态），不是每轮开始时的快照。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from studio.stages.common.scenes import CANVAS_EXEMPLAR
from studio.stages.common.score import AUDIO_EXEMPLAR


def prepare_turn(workdir: Path) -> None:
    exemplars = workdir / "upstream" / "exemplar"
    exemplars.mkdir(parents=True, exist_ok=True)
    for source in (AUDIO_EXEMPLAR, CANVAS_EXEMPLAR):
        shutil.copyfile(source, exemplars / source.name)
