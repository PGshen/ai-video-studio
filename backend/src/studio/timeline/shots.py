"""`produce` 阶段里模型自己写的两份文档：镜头划分 `shots.json` 与截取区间 `range.json`。

只做结构检查；`id` 合法与唯一、首尾相接、总长与音频的差值由 `build_timeline` 统一报告。
读文件由调用方负责。
"""

from __future__ import annotations

import math
from typing import Any, TypeGuard

from studio.timeline.build import TimedSectionInput

SHOTS_PATH = "animation/shots.json"
RANGE_PATH = "music/range.json"

SNAP_TOLERANCE = 0.001
"""相邻镜头的缝隙小于等于这个值（秒）时，把后一个镜头的起点贴到前一个的终点（取整误差）。"""
_TOLERANCE = 0.05


def _number(value: Any) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def parse_shots(doc: Any, errors: list[str]) -> list[TimedSectionInput] | None:
    """`{"shots": [{id, label?, start, end}]}` → 镜头列表；有问题时记入 `errors` 并返回 `None`。"""
    if not isinstance(doc, dict):
        errors.append(f'{SHOTS_PATH}：顶层必须是对象 {{"shots": [...]}}')
        return None
    raw = doc.get("shots")
    if not isinstance(raw, list):
        errors.append(f"{SHOTS_PATH}：缺少 shots 列表")
        return None
    if not raw:
        errors.append(f"{SHOTS_PATH}：shots 里至少要有一个镜头")
        return None
    shots: list[TimedSectionInput] = []
    problems = len(errors)
    for index, item in enumerate(raw):
        where = f"{SHOTS_PATH}：第 {index + 1} 个镜头"
        if not isinstance(item, dict):
            errors.append(f"{where}必须是对象")
            continue
        shot_id, label = item.get("id"), item.get("label", item.get("id"))
        start, end = item.get("start"), item.get("end")
        if not isinstance(shot_id, str) or not shot_id:
            errors.append(f"{where}缺少字符串 id")
            continue
        if not isinstance(label, str):
            errors.append(f"{where}（{shot_id}）的 label 必须是字符串")
            continue
        if not _number(start) or not _number(end):
            errors.append(
                f"{where}（{shot_id}）的 start、end 必须是数字（当前 {start!r}、{end!r}）"
            )
            continue
        if shots and 0 < start - shots[-1].end <= SNAP_TOLERANCE:
            start = shots[-1].end
        shots.append(TimedSectionInput(shot_id, label, float(start), float(end)))
    return shots if len(errors) == problems else None


def parse_range(doc: Any, audio_duration: float, errors: list[str]) -> tuple[float, float] | None:
    """`music/range.json` → `(start, end)`（源文件里的全局秒）。

    `doc` 为 `None`（文件不存在）表示整首歌。要求 `0 ≤ start < end ≤ audio_duration`，
    **不要求落在强拍上**。
    """
    if doc is None:
        return 0.0, float(audio_duration)
    if not isinstance(doc, dict):
        errors.append(f'{RANGE_PATH}：顶层必须是对象 {{"start": 秒, "end": 秒}}')
        return None
    start, end = doc.get("start"), doc.get("end")
    if not _number(start) or not _number(end):
        errors.append(f"{RANGE_PATH}：start、end 必须是数字（当前 {start!r}、{end!r}）")
        return None
    if start < 0 or not start < end:
        errors.append(f"{RANGE_PATH}：需要 0 ≤ start < end（当前 {start}→{end}）")
        return None
    if end > audio_duration + _TOLERANCE:
        errors.append(f"{RANGE_PATH}：end {end} 超出音频时长 {audio_duration:.3f} 秒")
        return None
    return float(start), float(min(end, audio_duration))
