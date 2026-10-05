"""`music` 阶段：合成形态与导入形态共用阶段键，按工作区内容分流（4A 设计 §6.1）。

阶段拿不到项目设置，所以工作区里有 `music/source.<ext>` 即为导入形态；`tools()` 是两种形态的超集，
工具在错误形态下返回明确提示。

- 合成形态：agent 写 NumPy 合成脚本 `music/compose.py`，`render_music` 运行并返回图与指标；
  定稿条件是渲染记录与当前脚本、当前时间轴、当前音频一致（子项目 3 设计 §7.1）。
- 导入形态：`analyze_music` 写 `analysis.json`/`analysis.png`，agent 写 `music/sections.json`；
  定稿条件是分析结果对应当前源文件、`sections.json` 通过 `check_sections`。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from studio.agent.tools import ToolSpec
from studio.stages.common import SUGGEST_UPSTREAM_CHANGE_TOOL
from studio.stages.music.analyze import ANALYZE_MUSIC_TOOL
from studio.stages.music.prepare import prepare_turn
from studio.stages.music.sources import SOURCE_EXTENSIONS, import_source, infer_sources
from studio.stages.music.tool import RENDER_MUSIC_TOOL
from studio.stages.music.validate_sections import (
    ANALYSIS_PATH,
    SECTIONS_PATH,
    VALIDATE_SECTIONS_TOOL,
    check_sections,
)
from studio.timeline import TimelineError
from studio.timeline.load import load_timeline
from studio.workspace.scope import WriteScope

_PROMPT_PATH = Path(__file__).parent / "prompt.md"
_WRITE_SCOPE = WriteScope(
    writable=["music/compose.py", SECTIONS_PATH],
    tool_managed=[
        "music/music.wav",
        "music/events.json",
        "music/analysis.json",
        "music/analysis.png",
        "music/render.json",
        *(f"music/source.{ext}" for ext in SOURCE_EXTENSIONS),  # written by the upload endpoint
    ],
)
_TOOLS: list[ToolSpec] = [
    RENDER_MUSIC_TOOL,
    ANALYZE_MUSIC_TOOL,
    VALIDATE_SECTIONS_TOOL,
    SUGGEST_UPSTREAM_CHANGE_TOOL,
]
_RERENDER = "，需要重新调用 render_music"
_NOTHING_YET = "还没有配乐：合成形态请写 music/compose.py 并 render_music；导入形态请先上传歌曲"
_REANALYSE = "源文件已更换，需要重新 analyze_music"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_object(path: Path) -> dict | None:
    """`path` 的 JSON 对象；不存在、无法解析或顶层不是对象时为 `None`。"""
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return record if isinstance(record, dict) else None


def _render_record(workdir: Path) -> dict | None:
    return _read_object(workdir / "music" / "render.json")


def _current_analysis(workdir: Path, source: Path) -> dict | None:
    """与当前源文件对应的 `analysis.json`；缺失、损坏或源文件已更换时为 `None`。"""
    analysis = _read_object(workdir / ANALYSIS_PATH)
    if analysis is None or analysis.get("source_hash") != _sha256(source):
        return None
    return analysis


def _import_blockers(workdir: Path, source: Path) -> list[str]:
    analysis_path = workdir / ANALYSIS_PATH
    sections_path = workdir / SECTIONS_PATH
    blockers: list[str] = []
    analysis = _read_object(analysis_path)
    if analysis is None:
        blockers.append(f"{ANALYSIS_PATH} 缺失或无法读取，需要先调用 analyze_music")
    elif analysis.get("source_hash") != _sha256(source):
        blockers.append(_REANALYSE)
    if not sections_path.is_file():
        blockers.append(f"{SECTIONS_PATH} 不存在：写出段落后用 validate_sections 校验")
    if blockers:
        return blockers
    try:
        doc = json.loads(sections_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [f"{SECTIONS_PATH} 不是合法的 JSON：{exc}"]
    return list(check_sections(doc, analysis).errors)


def _import_status(workdir: Path, source: Path) -> str:
    analysis = _current_analysis(workdir, source)
    if analysis is None:
        return "未分析"
    doc = _read_object(workdir / SECTIONS_PATH)
    if doc is None:
        return "已分析，待写 sections.json"
    sections = doc.get("sections")
    count = len(sections) if isinstance(sections, list) else 0
    try:
        return (
            f"已分析：BPM {float(analysis['bpm']):g}，{float(analysis['duration']):.2f} 秒，"
            f"置信度 {float(analysis['confidence']):.2f}；{count} 个段落"
        )
    except (KeyError, TypeError, ValueError):
        return "未分析"


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
        source = import_source(workdir)
        if source is not None:
            return _import_blockers(workdir, source)
        record = _render_record(workdir)
        if record is None:
            return [_NOTHING_YET]
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
        source = import_source(workdir)
        if source is not None:
            return _import_status(workdir, source)
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
