"""`produce` 阶段的 `prepare_turn`：复制金样本（有歌词时多一份歌词画面的样本）。

不再生成 `upstream/timeline.json`：镜头划分和配乐都由本阶段自己写，改一处就要立刻反映到另一处，
所以时间轴由各工具即时构建（`timeline.load` 的 `produce` 形态），不是每轮开始时的快照。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from studio.stages.common.scenes import CANVAS_EXEMPLAR, LYRICS_EXEMPLAR
from studio.stages.common.score import AUDIO_EXEMPLAR
from studio.timeline.lyrics import LYRICS_PATH


def prepare_turn(workdir: Path) -> None:
    exemplars = workdir / "upstream" / "exemplar"
    exemplars.mkdir(parents=True, exist_ok=True)
    sources = [AUDIO_EXEMPLAR, CANVAS_EXEMPLAR]
    lyrics = exemplars / LYRICS_EXEMPLAR.name
    if (workdir / LYRICS_PATH).is_file():
        sources.append(LYRICS_EXEMPLAR)
    else:
        lyrics.unlink(missing_ok=True)  # the lyrics were deleted since an earlier turn
    for source in sources:
        shutil.copyfile(source, exemplars / source.name)
