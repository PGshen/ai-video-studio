"""`engines.tts` 测试（计划 M3 T1）：Volcengine 引擎，全程挡住真实网络。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from studio.engines.tts.base import TTSRequest, TTSResult, WordTimestamp
from studio.engines.tts.factory import build_tts_engine
from studio.engines.tts.voice_map import resolve_speaker
from studio.engines.tts.volcengine import VolcengineTTSEngine

_TINY_MP3 = (Path(__file__).parents[1] / "fixtures" / "tts" / "tiny.mp3").read_bytes()
_ENDPOINT = "https://tts.test/synthesize"


def _sse_body(*chunks: dict) -> bytes:
    return b"\n".join(json.dumps(chunk).encode("utf-8") for chunk in chunks) + b"\n"


def _audio_chunk(data: bytes, words: list[dict] | None = None) -> dict:
    chunk: dict = {"code": 0, "data": base64.b64encode(data).decode("ascii")}
    if words is not None:
        chunk["sentence"] = {"words": words}
    return chunk


def test_tts_request_defaults() -> None:
    request = TTSRequest(text="你好")
    assert request.voice == "default"
    assert request.speed == 1.0


def test_tts_result_defaults_to_empty_audio_and_timestamps() -> None:
    result = TTSResult(success=True, output_path=None, duration_seconds=1.2, error_message=None)
    assert result.audio_bytes == b""
    assert result.word_timestamps == []


def test_word_timestamp_optional_confidence() -> None:
    timestamp = WordTimestamp(word="你好", start_time=0.0, end_time=0.5)
    assert timestamp.confidence is None


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_success_concatenates_audio_and_collects_timestamps() -> None:
    body = _sse_body(
        _audio_chunk(
            _TINY_MP3[: len(_TINY_MP3) // 2],
            words=[{"word": "你好", "startTime": 0.0, "endTime": 0.3}],
        ),
        _audio_chunk(
            _TINY_MP3[len(_TINY_MP3) // 2 :],
            words=[{"word": "世界", "startTime": 0.3, "endTime": 0.6}],
        ),
    )
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, content=body))
    engine = VolcengineTTSEngine(api_key="k", endpoint=_ENDPOINT, max_retries=0)

    result = await engine.synthesize(TTSRequest(text="你好世界", voice="zizi"))

    assert result.success
    assert result.audio_bytes == _TINY_MP3
    assert result.duration_seconds is not None
    assert [w.word for w in result.word_timestamps] == ["你好", "世界"]
    assert result.word_timestamps[0].start_time == 0.0
    # 时间戳按真实 mp3 时长夹紧（volcengine.py 的既有行为）：给的 0.6s 超过
    # 真实解析出的时长时，取真实时长本身。
    assert result.word_timestamps[1].end_time == min(0.6, result.duration_seconds)


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_retries_on_5xx_then_succeeds() -> None:
    route = respx.post(_ENDPOINT)
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, content=_sse_body(_audio_chunk(_TINY_MP3))),
    ]
    engine = VolcengineTTSEngine(
        api_key="k", endpoint=_ENDPOINT, max_retries=1, retry_base_delay_seconds=0.0
    )

    result = await engine.synthesize(TTSRequest(text="你好", voice="zizi"))

    assert result.success
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_exhausts_retries_and_fails() -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(500))
    engine = VolcengineTTSEngine(
        api_key="k", endpoint=_ENDPOINT, max_retries=2, retry_base_delay_seconds=0.0
    )

    result = await engine.synthesize(TTSRequest(text="你好", voice="zizi"))

    assert not result.success
    assert "500" in (result.error_message or "")


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_does_not_retry_non_retryable_api_error() -> None:
    route = respx.post(_ENDPOINT)
    route.mock(
        return_value=httpx.Response(
            200, content=_sse_body({"code": 1001, "message": "invalid speaker xyz"})
        )
    )
    engine = VolcengineTTSEngine(
        api_key="k", endpoint=_ENDPOINT, max_retries=2, retry_base_delay_seconds=0.0
    )

    result = await engine.synthesize(TTSRequest(text="你好", voice="zizi"))

    assert not result.success
    assert "invalid speaker" in (result.error_message or "")
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_uses_voices_override_when_provided() -> None:
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse_body(_audio_chunk(_TINY_MP3)))

    respx.post(_ENDPOINT).mock(side_effect=_capture)
    engine = VolcengineTTSEngine(
        api_key="k",
        endpoint=_ENDPOINT,
        max_retries=0,
        voices={"my-alias": "custom_speaker_id"},
    )

    result = await engine.synthesize(TTSRequest(text="你好", voice="my-alias"))

    assert result.success
    assert captured["body"]["req_params"]["speaker"] == "custom_speaker_id"


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_unknown_voice_without_override_raises() -> None:
    engine = VolcengineTTSEngine(api_key="k", endpoint=_ENDPOINT, max_retries=0)

    with pytest.raises(ValueError, match="zzz"):
        await engine.synthesize(TTSRequest(text="你好", voice="zzz"))


def test_build_tts_engine_reads_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOLCENGINE_TTS_API_KEY", "real-key")

    engine = build_tts_engine()

    assert isinstance(engine, VolcengineTTSEngine)
    assert engine._api_key == "real-key"
    assert engine._resource_id == "seed-tts-2.0"
    assert engine._engine == "doubao_2.0"


def test_build_tts_engine_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOLCENGINE_TTS_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="VOLCENGINE_TTS_API_KEY"):
        build_tts_engine()


def test_resolve_speaker_known_alias() -> None:
    assert resolve_speaker("zizi", "doubao_2.0") == "zh_female_qingchezizi_uranus_bigtts"


def test_resolve_speaker_unknown_alias() -> None:
    with pytest.raises(ValueError, match="zzz"):
        resolve_speaker("zzz", "doubao_2.0")


def test_resolve_speaker_unknown_engine() -> None:
    with pytest.raises(ValueError, match="engine-x"):
        resolve_speaker("zizi", "engine-x")
