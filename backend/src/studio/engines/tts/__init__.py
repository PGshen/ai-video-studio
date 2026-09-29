"""语音合成引擎（设计 §5.2；计划 M3 T1）：Volcengine TTS 与 beat 对齐。"""

from __future__ import annotations

from studio.engines.tts.base import TTSEngine, TTSRequest, TTSResult, WordTimestamp
from studio.engines.tts.beat_aligner import align_scene_beats
from studio.engines.tts.factory import build_tts_engine
from studio.engines.tts.text_normalize import normalize_alignment_text
from studio.engines.tts.volcengine import VolcengineTTSEngine

__all__ = [
    "TTSEngine",
    "TTSRequest",
    "TTSResult",
    "WordTimestamp",
    "VolcengineTTSEngine",
    "build_tts_engine",
    "align_scene_beats",
    "normalize_alignment_text",
]
