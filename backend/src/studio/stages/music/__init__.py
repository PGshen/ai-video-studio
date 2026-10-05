"""`music` 阶段（合成形态）：agent 写 NumPy 合成脚本，`render_music` 运行并返回图与指标。

可写 `music/compose.py`；`music.wav`、`events.json`、`analysis.json`、`analysis.png`、`render.json`
由工具托管。定稿条件：渲染记录与当前脚本、当前时间轴、当前音频一致（子项目 3 设计 §7.1）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.common import SUGGEST_UPSTREAM_CHANGE_TOOL
from studio.stages.music.prepare import prepare_turn
from studio.stages.music.sources import infer_sources
from studio.stages.music.tool import RENDER_MUSIC_TOOL
from studio.timeline import TimelineError
from studio.timeline.load import load_timeline
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(
    writable=["music/compose.py"],
    tool_managed=[
        "music/music.wav",
        "music/events.json",
        "music/analysis.json",
        "music/analysis.png",
        "music/render.json",
    ],
)
_TOOLS: list[ToolSpec] = [RENDER_MUSIC_TOOL, SUGGEST_UPSTREAM_CHANGE_TOOL]
_RERENDER = "，需要重新调用 render_music"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render_record(workdir: Path) -> dict | None:
    path = workdir / "music" / "render.json"
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


class MusicStage:
    name = "music"
    allow_web = False
    workspaceless = False

    def system_prompt(self) -> str:
        return _PROMPT_PATH.read_text(encoding="utf-8")

    def tools(self) -> list[ToolSpec]:
        return list(_TOOLS)

    def write_scope(self) -> WriteScope:
        return _WRITE_SCOPE

    def reads(self) -> list[str]:
        return ["concept", "narrative", "beatsheet"]

    def prepare_turn(self, workdir: Path) -> None:
        prepare_turn(workdir)

    def artifact_dirs(self) -> list[str]:
        return ["music"]

    def finalize_blockers(self, workdir: Path) -> list[str]:
        record = _render_record(workdir)
        if record is None:
            return ["还没有渲染配乐：先写 music/compose.py 并调用 render_music"]
        blockers: list[str] = []
        script = workdir / "music" / "compose.py"
        if not script.is_file() or _sha256(script) != record.get("script_hash"):
            blockers.append("music/compose.py 在上次渲染之后改过（或已删除）" + _RERENDER)
        wav = workdir / "music" / "music.wav"
        if not wav.is_file() or _sha256(wav) != record.get("wav_hash"):
            blockers.append("music/music.wav 缺失或与渲染记录不一致" + _RERENDER)
        try:
            loaded = load_timeline(infer_sources(workdir, "upstream/", with_music=False))
        except TimelineError as exc:
            blockers.append("时间轴不可用：" + "；".join(exc.errors))
        else:
            if loaded.base_hash != record.get("base_hash"):
                blockers.append("上游的节拍脚本或叙事时间轴在上次渲染之后变了" + _RERENDER)
        return blockers

    def status_summary(self, workdir: Path) -> str:
        record = _render_record(workdir)
        if record is None:
            return "未渲染"
        events = workdir / "music" / "events.json"
        count = 0
        if events.is_file():
            try:
                count = len(json.loads(events.read_text(encoding="utf-8")).get("events", []))
            except (ValueError, AttributeError):
                count = 0
        seconds = float(record.get("duration", 0))
        return f"已渲染：{seconds:.2f} 秒，BPM {record.get('bpm')}，{count} 个事件"


STAGE = MusicStage()
