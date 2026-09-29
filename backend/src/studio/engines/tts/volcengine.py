"""Volcengine（火山引擎）TTS 引擎（设计 §5.2；计划 M3 T1）。

迁移自 `../ai-video/backend/app/engines/tts/volcengine.py`：流式解析、
重试判定、mp3 时长解析的逻辑不变，只改 import 路径。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import uuid
from io import BytesIO

import httpx
from mutagen.mp3 import MP3

from studio.engines.tts.base import TTSRequest, TTSResult, WordTimestamp
from studio.engines.tts.voice_map import resolve_speaker

_TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
_RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429}
_NON_RETRYABLE_API_ERROR_MARKERS = (
    "api key",
    "authentication",
    "authorization",
    "invalid parameter",
    "invalid speaker",
    "permission denied",
    "quota exhausted",
    "unauthorized",
    "unsupported speaker",
)

logger = logging.getLogger(__name__)


def _parse_mp3_duration(audio_bytes: bytes) -> float | None:
    try:
        audio = MP3(BytesIO(audio_bytes))
        return audio.info.length
    except Exception:
        return None


class VolcengineTTSEngine:
    engine_name = "volcengine"

    def __init__(
        self,
        api_key: str,
        resource_id: str = "seed-tts-2.0",
        engine: str = "doubao_2.0",
        max_retries: int = 2,
        retry_base_delay_seconds: float = 1.0,
        endpoint: str = _TTS_URL,
        timeout_seconds: float = 60.0,
        voices: dict[str, str] | None = None,
    ):
        self._api_key = api_key
        self._resource_id = resource_id
        self._engine = engine
        self._max_retries = max(0, max_retries)
        self._retry_base_delay_seconds = max(0.0, retry_base_delay_seconds)
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._voices = voices

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        total_attempts = self._max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                result, retryable = await self._synthesize_once(request)
            except httpx.RequestError as exc:
                result = self._failure_result(f"TTS request failed: {type(exc).__name__}: {exc}")
                retryable = True

            if result.success or not retryable or attempt == total_attempts:
                return result

            delay = self._retry_base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Volcengine TTS request failed; retrying: attempt=%d/%d retry_in=%.1fs error=%s",
                attempt,
                total_attempts,
                delay,
                result.error_message,
            )
            await asyncio.sleep(delay)

        raise RuntimeError("unreachable")

    async def _synthesize_once(self, request: TTSRequest) -> tuple[TTSResult, bool]:
        if self._voices is None:
            speaker = resolve_speaker(request.voice, self._engine)
        else:
            try:
                speaker = self._voices[request.voice]
            except KeyError as exc:
                raise ValueError(
                    f"Voice {request.voice!r} is not available for {self._engine}"
                ) from exc
        headers = {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }
        body = {
            "req_params": {
                "text": request.text,
                "speaker": speaker,
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": 24000,
                    # 火山引擎以 -50 至 100 的相对值表示语速；项目倍速 1.0 对应 0。
                    "speech_rate": round((request.speed - 1.0) * 100),
                },
            }
        }
        if self._resource_id == "seed-tts-1.0":
            body["req_params"]["audio_params"]["enable_timestamp"] = True
        else:
            body["req_params"]["audio_params"]["enable_subtitle"] = True

        audio_chunks: list[bytes] = []
        word_timestamps: list[WordTimestamp] = []
        timestamp_keys: set[tuple[str, float, float]] = set()
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            async with client.stream("POST", self._endpoint, json=body, headers=headers) as resp:
                if not 200 <= resp.status_code < 300:
                    retryable = (
                        resp.status_code in _RETRYABLE_HTTP_STATUS_CODES or resp.status_code >= 500
                    )
                    return (
                        self._failure_result(f"TTS HTTP request failed (HTTP {resp.status_code})"),
                        retryable,
                    )
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        return (
                            self._failure_result(
                                f"TTS chunk parse failed (HTTP {resp.status_code}): {line[:100]}"
                            ),
                            True,
                        )
                    if not isinstance(chunk, dict):
                        return (
                            self._failure_result(
                                f"TTS chunk has unexpected type: {type(chunk).__name__}"
                            ),
                            True,
                        )
                    code = chunk.get("code", 0)
                    if code != 0:
                        if code == 20000000:
                            continue
                        message = str(chunk.get("message") or f"TTS API error code {code}")
                        return (
                            self._failure_result(message),
                            self._is_retryable_api_error(message),
                        )
                    audio_data = chunk.get("data", "")
                    if audio_data:
                        try:
                            audio_chunks.append(base64.b64decode(audio_data, validate=True))
                        except (binascii.Error, TypeError, ValueError):
                            return (
                                self._failure_result("TTS API returned invalid audio data"),
                                True,
                            )
                    sentence = chunk.get("sentence") or {}
                    for item in sentence.get("words") or []:
                        try:
                            word = str(item["word"])
                            start_time = float(item["startTime"])
                            end_time = float(item["endTime"])
                        except (KeyError, TypeError, ValueError):
                            continue
                        key = (word, round(start_time, 6), round(end_time, 6))
                        if key in timestamp_keys:
                            continue
                        timestamp_keys.add(key)
                        confidence = item.get("confidence")
                        word_timestamps.append(
                            WordTimestamp(
                                word=word,
                                start_time=max(0.0, start_time),
                                end_time=max(0.0, end_time),
                                confidence=float(confidence) if confidence is not None else None,
                            )
                        )

        if not audio_chunks:
            return self._failure_result("TTS API returned empty audio data"), True

        audio_bytes = b"".join(audio_chunks)
        duration = _parse_mp3_duration(audio_bytes)
        word_timestamps.sort(key=lambda item: (item.start_time, item.end_time))
        if duration is not None:
            for item in word_timestamps:
                item.start_time = min(item.start_time, duration)
                item.end_time = min(max(item.end_time, item.start_time), duration)
        return (
            TTSResult(
                success=True,
                output_path=None,
                duration_seconds=duration,
                error_message=None,
                audio_bytes=audio_bytes,
                word_timestamps=word_timestamps,
            ),
            False,
        )

    @staticmethod
    def _failure_result(message: str) -> TTSResult:
        return TTSResult(
            success=False,
            output_path=None,
            duration_seconds=None,
            error_message=message,
            audio_bytes=b"",
        )

    @staticmethod
    def _is_retryable_api_error(message: str) -> bool:
        normalized = message.casefold()
        return not any(marker in normalized for marker in _NON_RETRYABLE_API_ERROR_MARKERS)

    async def health_check(self) -> bool:
        if self._voices:
            voice = next(iter(self._voices))
        else:
            voice = "sisi" if self._engine == "doubao_1.0" else "zizi"
        result = await self.synthesize(TTSRequest(text="测试", voice=voice))
        return result.success
