"""Beat 对齐（设计 §5.2；计划 M3 T2）：把 TTS 逐字时间戳对齐到每个 beat。

迁移自 `../ai-video/backend/app/services/beat_aligner.py`，适配新 narrative
schema 的两处改动：

- 不再有 `scene_index`：报错信息改用调用方传入的 `scene_id`（可选）。
- 不再有 `fallback_weight`：`_interpolate_missing_beats` 原本按这个字段
  加权分摊插值区间，新 schema 没有这个产物字段，改成固定权重 1.0（等权重
  插值），这是对旧系统的简化迁移（M3 计划决策记录）。
"""

from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass
from typing import Any

from studio.engines.tts.text_normalize import normalize_alignment_text

ANIMATION_PREROLL_SECONDS = 0.18
ANIMATION_POSTROLL_SECONDS = 0.12


@dataclass(frozen=True)
class _NormalizedText:
    text: str
    original_indices: list[int]


def _normalize_with_indices(text: str) -> _NormalizedText:
    chars: list[str] = []
    indices: list[int] = []
    for original_index, original_char in enumerate(text):
        normalized = normalize_alignment_text(unicodedata.normalize("NFKC", original_char))
        for char in normalized:
            chars.append(char)
            indices.append(original_index)
    return _NormalizedText("".join(chars), indices)


def _build_tts_chars(
    timestamps: list[dict[str, Any]],
) -> tuple[str, list[int], list[dict[str, Any]]]:
    text_chars: list[str] = []
    char_to_token: list[int] = []
    valid_tokens: list[dict[str, Any]] = []
    for source in timestamps:
        try:
            word = str(source["word"])
            start_time = float(source["start_time"])
            end_time = float(source["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        normalized_word = normalize_alignment_text(word)
        if not normalized_word:
            continue
        token_index = len(valid_tokens)
        valid_tokens.append(
            {
                **source,
                "word": word,
                "start_time": max(0.0, start_time),
                "end_time": max(start_time, end_time),
            }
        )
        text_chars.extend(normalized_word)
        char_to_token.extend([token_index] * len(normalized_word))
    return "".join(text_chars), char_to_token, valid_tokens


def _character_mapping(source_text: str, target_text: str) -> dict[int, int]:
    matcher = difflib.SequenceMatcher(a=source_text, b=target_text, autojunk=False)
    mapping: dict[int, int] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = block.b + offset
    return mapping


def _interpolate_missing_beats(beats: list[dict[str, Any]], duration: float) -> None:
    index = 0
    while index < len(beats):
        if beats[index].get("speech_start_seconds") is not None:
            index += 1
            continue

        gap_start = index
        while index < len(beats) and beats[index].get("speech_start_seconds") is None:
            index += 1
        gap_end = index

        left = (
            float(beats[gap_start - 1]["speech_end_seconds"])
            if gap_start > 0 and beats[gap_start - 1].get("speech_end_seconds") is not None
            else 0.0
        )
        right = (
            float(beats[gap_end]["speech_start_seconds"])
            if gap_end < len(beats) and beats[gap_end].get("speech_start_seconds") is not None
            else duration
        )
        right = max(left, right)
        # 新 schema 没有 fallback_weight，统一等权重分摊间隙时长。
        beat_count = gap_end - gap_start
        cursor = left
        for beat_index in range(gap_start, gap_end):
            end = right if beat_index == gap_end - 1 else cursor + (right - left) / beat_count
            beats[beat_index]["speech_start_seconds"] = cursor
            beats[beat_index]["speech_end_seconds"] = end
            beats[beat_index]["alignment_status"] = "interpolated"
            cursor = end


def align_scene_beats(scene: dict[str, Any], *, scene_id: str | None = None) -> dict[str, Any]:
    """对一个镜头的 `beats` 做字符级对齐，返回补全了对齐字段的镜头 dict。

    `scene` 需要 `narration`（全文）、`beats`（每项至少有 `cue_text`）、
    `duration_seconds`、`word_timestamps`（TTS 返回的逐字时间戳，
    `{"word","start_time","end_time"}`）。
    """
    label = scene_id if scene_id is not None else scene.get("id", "?")
    beats = [dict(beat) for beat in scene.get("beats") or []]
    if not beats:
        raise ValueError(f"镜头 {label} 的 beats 不能为空")

    duration_value = scene.get("duration_seconds")
    if duration_value is None:
        return {
            **scene,
            "beats": [{**beat, "alignment_status": "failed"} for beat in beats],
            "alignment_coverage": 0.0,
        }
    duration = max(0.0, float(duration_value))

    narration = str(scene.get("narration", ""))
    normalized_narration = _normalize_with_indices(narration)
    normalized_cursor = 0
    for beat in beats:
        cue = normalize_alignment_text(str(beat.get("cue_text", "")))
        cue_start = normalized_cursor
        cue_end = cue_start + len(cue)
        if normalized_narration.text[cue_start:cue_end] != cue:
            raise ValueError(f"镜头 {label} 的 beats.cue_text 未能拼接覆盖 narration")
        beat["_normalized_start"] = cue_start
        beat["_normalized_end"] = cue_end
        normalized_cursor = cue_end

    tts_text, tts_char_to_token, valid_tokens = _build_tts_chars(
        list(scene.get("word_timestamps") or [])
    )
    mapping = _character_mapping(normalized_narration.text, tts_text) if tts_text else {}
    coverage = len(mapping) / len(normalized_narration.text) if normalized_narration.text else 1.0

    for beat in beats:
        token_indices = {
            tts_char_to_token[mapping[source_index]]
            for source_index in range(beat["_normalized_start"], beat["_normalized_end"])
            if source_index in mapping and mapping[source_index] < len(tts_char_to_token)
        }
        if token_indices:
            first_token = valid_tokens[min(token_indices)]
            last_token = valid_tokens[max(token_indices)]
            beat["speech_start_seconds"] = min(duration, float(first_token["start_time"]))
            beat["speech_end_seconds"] = min(duration, float(last_token["end_time"]))
            beat["alignment_status"] = "aligned"
        else:
            beat["speech_start_seconds"] = None
            beat["speech_end_seconds"] = None
            beat["alignment_status"] = "pending"

    _interpolate_missing_beats(beats, duration)

    for beat in beats:
        speech_start = min(duration, max(0.0, float(beat["speech_start_seconds"])))
        speech_end = min(duration, max(speech_start, float(beat["speech_end_seconds"])))
        beat["speech_start_seconds"] = round(speech_start, 6)
        beat["speech_end_seconds"] = round(speech_end, 6)
        beat["animation_start_seconds"] = round(
            max(0.0, speech_start - ANIMATION_PREROLL_SECONDS), 6
        )
        beat["animation_end_seconds"] = round(
            min(duration, speech_end + ANIMATION_POSTROLL_SECONDS), 6
        )
        beat.pop("_normalized_start", None)
        beat.pop("_normalized_end", None)

    return {**scene, "beats": beats, "alignment_coverage": round(coverage, 6)}
