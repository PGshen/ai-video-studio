"""`music` 阶段的 `prepare_turn`（子项目 3 设计 §7.1）。

合成形态：生成 `upstream/timeline.json`（不含 `music` 层，是合成脚本的输入）并复制金样本。可预期的
错误（上游缺失、文件损坏、各层不一致）不抛异常——TurnRunner 会把它变成整轮失败；改为删除旧的
`timeline.json` 并写 `timeline.error.txt`，由工具和提示词向 agent 说明。

导入形态（工作区里有 `music/source.<ext>`，4A 设计 §6.1）：时间轴来自歌曲本身，不需要上游时间轴
和金样本；只清掉旧的 `timeline.json`/`timeline.error.txt`，免得 agent 误读。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from studio.stages.common.score import AUDIO_EXEMPLAR
from studio.stages.common.score.sources import import_source, infer_sources
from studio.timeline import TimelineError
from studio.timeline.load import load_timeline

_EXEMPLAR = AUDIO_EXEMPLAR
TIMELINE_PATH = "upstream/timeline.json"
ERROR_PATH = "upstream/timeline.error.txt"
_NO_UPSTREAM = (
    "缺少上游产物：短片需要节拍脚本（beatsheet）定稿；"
    "有旁白的讲解需要叙事（narrative）定稿并完成配音；音乐 MV 请先上传歌曲"
)


def _fail(workdir: Path, reason: str) -> None:
    (workdir / TIMELINE_PATH).unlink(missing_ok=True)
    error = workdir / ERROR_PATH
    error.parent.mkdir(parents=True, exist_ok=True)
    error.write_text(reason + "\n", encoding="utf-8")


def prepare_turn(workdir: Path) -> None:
    if import_source(workdir) is not None:
        (workdir / TIMELINE_PATH).unlink(missing_ok=True)
        (workdir / ERROR_PATH).unlink(missing_ok=True)
        return
    exemplar = workdir / "upstream" / "exemplar" / _EXEMPLAR.name
    exemplar.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_EXEMPLAR, exemplar)

    upstream = workdir / "upstream"
    if not (
        (upstream / "beatsheet" / "beatsheet.json").is_file()
        or (upstream / "narrative" / "narrative.json").is_file()
    ):
        _fail(workdir, _NO_UPSTREAM)
        return
    try:
        loaded = load_timeline(infer_sources(workdir, "upstream/", with_music=False))
    except TimelineError as exc:
        _fail(workdir, "；".join(exc.errors))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        _fail(workdir, f"上游产物的结构不符合预期：{type(exc).__name__}: {exc}")
    else:
        (workdir / ERROR_PATH).unlink(missing_ok=True)
        (workdir / TIMELINE_PATH).write_text(
            json.dumps(loaded.timeline.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
