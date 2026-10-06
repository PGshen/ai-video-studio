"""`analyze_music` 工具（4A 设计 §4）：分析 `music/source.*`，写 `analysis.json` 与 `analysis.png`。

分析在隔离子进程里跑（`engines.audio.song_job`），产物先落在临时目录，成功后才换进 `music/`；
失败（无法解码、静音、超时）不动 `music/` 里的旧产物。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from studio.agent.events import ImageData
from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.engines.audio.song import CONFIDENCE_WARN
from studio.engines.audio.song_job import DEFAULT_TIMEOUT, SongJobError, run_song_analysis
from studio.stages.music.sources import import_source
from studio.stages.music.tool import LISTEN_NOTE, compress_picture

NO_SOURCE_MESSAGE = "还没有上传音乐，请让用户在音乐画布上传"
NO_SOURCE_PRODUCE_MESSAGE = "还没有上传歌曲：这个项目没有可分析的音乐，请让用户先上传歌曲"
_PRODUCE_STAGES = ("concept", "produce")
RESIDUAL_WARN_MS = 30.0
_PRODUCTS = ("analysis.json", "analysis.png")
_MAX_CANDIDATES = 24


def _install(temp_dir: Path, music_dir: Path) -> None:
    """Replace the products in `music/`; copy each to a sibling, then rename."""
    music_dir.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, Path]] = []
    try:
        for name in _PRODUCTS:
            hidden = music_dir / f".{name}.tmp"
            shutil.copyfile(temp_dir / name, hidden)
            staged.append((hidden, music_dir / name))
        for hidden, final in staged:
            os.replace(hidden, final)
    finally:
        for hidden, _ in staged:
            hidden.unlink(missing_ok=True)


def _summary(doc: dict[str, Any], *, produce: bool = False) -> str:
    candidates = [c for c in doc.get("candidates", []) if isinstance(c, int | float)]
    shown = ", ".join(f"{c:.2f}" for c in candidates[:_MAX_CANDIDATES])
    more = (
        f"（共 {len(candidates)} 个，仅列前 {_MAX_CANDIDATES} 个）"
        if len(candidates) > _MAX_CANDIDATES
        else ""
    )
    lines = [
        f"歌曲分析完成：BPM {doc['bpm']:g}，第一个强拍 {doc['offset']:.3f} 秒，"
        f"总时长 {doc['duration']:.2f} 秒。",
        f"拟合残差 {doc['residual_ms']:.1f} ms，置信度 {doc['confidence']:.2f}。",
        f"候选段落边界（强拍，秒）：{shown or '无'}{more}",
    ]
    warnings = list(doc.get("warnings", []))
    low_confidence = doc["confidence"] < CONFIDENCE_WARN or doc["residual_ms"] > RESIDUAL_WARN_MS
    if low_confidence and produce:
        lines.append(
            "置信度低或拟合残差大：自动网格与分段只是参考，请对照分析图自己判断节拍；"
            "需要截取时写 music/range.json。"
        )
    elif low_confidence:
        lines.append(
            "置信度低或拟合残差大：自动网格与分段可能不准，请对照分析图手动修正 "
            "sections.json（含 bpm/offset）；这不阻止定稿。"
        )
    if warnings:
        lines.append(f"警告（{len(warnings)} 条）：")
        lines += [f"- {w}" for w in warnings]
    lines.append("分析图：波形、能量、网格、候选边界（见附图）。")
    lines.append(LISTEN_NOTE)
    return "\n".join(lines)


class AnalyzeMusicArgs(BaseModel):
    pass


async def _handler(ctx: ToolContext, args: AnalyzeMusicArgs) -> ToolResult:
    workdir = ctx.workdir.resolve()
    produce = ctx.stage in _PRODUCE_STAGES
    source = import_source(workdir)
    if source is None:
        message = NO_SOURCE_PRODUCE_MESSAGE if produce else NO_SOURCE_MESSAGE
        return ToolResult(text=message, is_error=True)
    # The child runs with cwd=out_dir, so both paths must be absolute and resolved.
    source = source.resolve()
    with tempfile.TemporaryDirectory(prefix="song-analysis-") as raw_temp:
        temp_dir = Path(raw_temp).resolve()
        try:
            result = await run_song_analysis(source, temp_dir, timeout=DEFAULT_TIMEOUT)
            doc = json.loads(result.analysis_path.read_text(encoding="utf-8"))
            summary = _summary(doc, produce=produce)
            jpeg = compress_picture(result.picture_path.read_bytes())  # before installing
            _install(temp_dir, workdir / "music")
        except SongJobError as exc:
            return ToolResult(text=f"{exc}（music/ 里的旧产物没有改动）", is_error=True)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return ToolResult(
                text=f"歌曲分析的产物无法使用：{exc}（music/ 里的旧产物没有改动）", is_error=True
            )
    for name in _PRODUCTS:
        relpath = f"music/{name}"
        ctx.record_tool_write(relpath, hashlib.sha256((workdir / relpath).read_bytes()).hexdigest())
    image = ImageData(media_type="image/jpeg", data_base64=base64.b64encode(jpeg).decode("ascii"))
    return ToolResult(text=summary, images=[image])


ANALYZE_MUSIC_TOOL = ToolSpec(
    name="analyze_music",
    description=(
        "分析用户上传的歌曲（music/source.*）：拟合恒定 BPM 与第一个强拍、找候选段落边界、"
        "算能量曲线，重写 music/analysis.json 与 analysis.png，并返回 BPM、拟合残差、置信度、"
        "总时长、候选边界和分析图。同一文件结果可复现；首次运行可能要几十秒。"
        "没有上传音乐时会报错。你听不到声音，靠这张图和指标判断。"
    ),
    input_model=AnalyzeMusicArgs,
    stages={"music", "concept", "produce"},
    handler=_handler,
)
