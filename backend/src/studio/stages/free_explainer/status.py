"""`free_explainer` 的当前产物状态（free-mode 设计 §4.2）：叙事、配音、场景、背景乐各一句。

只读工作区、从不抛异常：读不出的项写"还没有"或说明原因，让 agent 知道下一步该做什么。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from studio.stages.common.scenes.helpers import scene_exists
from studio.stages.common.timeline_source import load_live_narrated
from studio.timeline import TimelineError, narration_from_documents

_NARRATIVE = "narrative/narrative.json"
_TIMING = "narrative/timing.json"
_MAX_LISTED = 5


def _read_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _listed(items: Sequence[str]) -> str:
    shown = "、".join(items[:_MAX_LISTED])
    return shown + (f" 等 {len(items)} 项" if len(items) > _MAX_LISTED else "")


def _scene_ids(narrative: dict[str, Any]) -> list[str]:
    scenes = narrative.get("scenes")
    if not isinstance(scenes, list):
        return []
    return [s["id"] for s in scenes if isinstance(s, dict) and isinstance(s.get("id"), str)]


def _voice_line(narrative: dict[str, Any], timing: dict[str, Any] | None) -> tuple[str, bool]:
    if timing is None:
        return "还没有配音：叙事通过 validate_narrative 后调用 synthesize_tts", False
    try:
        narration_from_documents(narrative, timing)
    except TimelineError as exc:
        return f"配音与叙事不一致，需要重新配音：{_listed(exc.errors)}", False
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        return f"配音与叙事不一致，需要重新配音：{type(exc).__name__}", False
    return "配音与叙事一致", True


def _music_line(workdir: Path, voiced: bool) -> str | None:
    music = workdir / "music"
    if not (music / "compose.py").is_file() and not (music / "render.json").is_file():
        return None
    record = _read_object(music / "render.json")
    if record is None:
        return "背景乐还没渲染：写好 music/compose.py 后调用 render_music"
    if not voiced:
        return "背景乐状态未知：先让配音与叙事一致"
    try:
        current = load_live_narrated(workdir, with_music=False).base_hash
    except (TimelineError, KeyError, TypeError, AttributeError, ValueError):
        return "背景乐状态未知：时间轴不可用"
    if record.get("base_hash") != current:
        return "配乐过期：叙事或配音变了，需要重新 render_music"
    return "配乐与当前时间轴一致"


def status_summary(workdir: Path) -> str:
    narrative = _read_object(workdir / _NARRATIVE)
    if narrative is None:
        missing = not (workdir / _NARRATIVE).is_file()
        head = "还没有 narrative/narrative.json" if missing else "narrative.json 无法解析"
        return f"{head}；先和用户定下题目与结构，再写叙事"
    ids = _scene_ids(narrative)
    voice, voiced = _voice_line(narrative, _read_object(workdir / _TIMING))
    lines = [f"叙事 {len(ids)} 个镜头", voice]
    missing_scenes = [scene_id for scene_id in ids if not scene_exists(workdir, scene_id)]
    scenes = f"场景 {len(ids) - len(missing_scenes)}/{len(ids)}"
    lines.append(f"{scenes}，缺 {_listed(missing_scenes)}" if missing_scenes else scenes)
    music = _music_line(workdir, voiced)
    if music is not None:
        lines.append(music)
    return "；".join(lines)
