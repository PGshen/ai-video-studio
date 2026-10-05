"""从工作区顶层 `narrative/` 读出时间轴（worker 成片与预览端点共用，同一来源）。

只用 `pathlib` 读文件，不依赖 `studio.workspace`（本包是纯能力层）。所有问题——文件缺失、JSON
损坏、符号链接指向工作区外、叙事与 timing 不一致——都汇总成 `TimelineError`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio.timeline.build import (
    TimelineError,
    TimelineLayers,
    build_timeline,
    narration_from_documents,
    timeline_hash,
)
from studio.timeline.schema import Timeline

_NARRATIVE = "narrative/narrative.json"
_TIMING = "narrative/timing.json"


@dataclass(frozen=True, slots=True)
class LoadedTimeline:
    timeline: Timeline
    hash: str
    narrative: dict[str, Any]
    timing: dict[str, Any]


def _read_document(workdir: Path, relpath: str) -> dict[str, Any]:
    path = workdir / relpath
    if not path.is_file():
        raise TimelineError([f"{relpath} 不存在（叙事阶段需要先定稿并完成配音）"])
    if not path.resolve().is_relative_to(workdir.resolve()):
        raise TimelineError([f"{relpath} 指向工作区之外，不能读取"])
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TimelineError([f"{relpath} 无法解析：{exc}"]) from exc
    if not isinstance(document, dict):
        raise TimelineError([f"{relpath} 的顶层不是对象"])
    return document


def load_workspace_timeline(workdir: Path) -> LoadedTimeline:
    narrative = _read_document(workdir, _NARRATIVE)
    timing = _read_document(workdir, _TIMING)
    timeline = build_timeline(TimelineLayers(narration_from_documents(narrative, timing)))
    return LoadedTimeline(timeline, timeline_hash(timeline), narrative, timing)
