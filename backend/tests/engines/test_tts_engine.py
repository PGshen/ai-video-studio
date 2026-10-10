"""`engines.tts` 测试（计划 M3 T1）：Volcengine 引擎，全程挡住真实网络。"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from studio.engines.tts.base import TTSRequest, TTSResult, TTSVoiceSpec, WordTimestamp
from studio.engines.tts.factory import build_tts_engine
from studio.engines.tts.volcengine import VolcengineTTSEngine

_TINY_MP3 = (Path(__file__).parents[1] / "fixtures" / "tts" / "tiny.mp3").read_bytes()
_ENDPOINT = "https://tts.test/synthesize"
_V2 = TTSVoiceSpec(speaker_id="zh_female_qingchezizi_uranus_bigtts", engine="doubao_2.0")
_V1 = TTSVoiceSpec(speaker_id="zh_female_shuangkuaisisi_moon_bigtts", engine="doubao_1.0")
_VOICES = {"zizi": _V2, "sisi": _V1}


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
    engine = VolcengineTTSEngine(api_key="k", voices=_VOICES, endpoint=_ENDPOINT, max_retries=0)

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
        api_key="k", voices=_VOICES, endpoint=_ENDPOINT, max_retries=1, retry_base_delay_seconds=0.0
    )

    result = await engine.synthesize(TTSRequest(text="你好", voice="zizi"))

    assert result.success
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_exhausts_retries_and_fails() -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(500))
    engine = VolcengineTTSEngine(
        api_key="k", voices=_VOICES, endpoint=_ENDPOINT, max_retries=2, retry_base_delay_seconds=0.0
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
        api_key="k", voices=_VOICES, endpoint=_ENDPOINT, max_retries=2, retry_base_delay_seconds=0.0
    )

    result = await engine.synthesize(TTSRequest(text="你好", voice="zizi"))

    assert not result.success
    assert "invalid speaker" in (result.error_message or "")
    assert route.call_count == 1


def _capturing_route() -> dict:
    captured: dict = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["headers"] = request.headers
        return httpx.Response(200, content=_sse_body(_audio_chunk(_TINY_MP3)))

    respx.post(_ENDPOINT).mock(side_effect=_capture)
    return captured


@pytest.mark.asyncio
@respx.mock
async def test_v2_voice_uses_seed_tts_2_resource_and_subtitle_flag() -> None:
    captured = _capturing_route()
    engine = VolcengineTTSEngine(api_key="k", voices=_VOICES, endpoint=_ENDPOINT, max_retries=0)

    result = await engine.synthesize(TTSRequest(text="你好", voice="zizi", speed=1.2))

    assert result.success
    assert captured["headers"]["x-api-resource-id"] == "seed-tts-2.0"
    params = captured["body"]["req_params"]
    assert params["speaker"] == "zh_female_qingchezizi_uranus_bigtts"
    assert params["audio_params"]["enable_subtitle"] is True
    assert "enable_timestamp" not in params["audio_params"]
    assert params["audio_params"]["speech_rate"] == 20


@pytest.mark.asyncio
@respx.mock
async def test_v1_voice_uses_seed_tts_1_resource_and_timestamp_flag() -> None:
    captured = _capturing_route()
    engine = VolcengineTTSEngine(api_key="k", voices=_VOICES, endpoint=_ENDPOINT, max_retries=0)

    result = await engine.synthesize(TTSRequest(text="你好", voice="sisi"))

    assert result.success
    assert captured["headers"]["x-api-resource-id"] == "seed-tts-1.0"
    params = captured["body"]["req_params"]
    assert params["speaker"] == "zh_female_shuangkuaisisi_moon_bigtts"
    assert params["audio_params"]["enable_timestamp"] is True
    assert "enable_subtitle" not in params["audio_params"]


@pytest.mark.asyncio
@respx.mock
async def test_one_engine_instance_can_mix_both_versions() -> None:
    captured = _capturing_route()
    engine = VolcengineTTSEngine(api_key="k", voices=_VOICES, endpoint=_ENDPOINT, max_retries=0)

    await engine.synthesize(TTSRequest(text="你好", voice="sisi"))
    assert captured["headers"]["x-api-resource-id"] == "seed-tts-1.0"
    await engine.synthesize(TTSRequest(text="你好", voice="zizi"))
    assert captured["headers"]["x-api-resource-id"] == "seed-tts-2.0"


@pytest.mark.asyncio
@respx.mock
async def test_unsupported_engine_version_raises() -> None:
    bad = {"x": TTSVoiceSpec(speaker_id="s", engine="doubao_9.9")}
    engine = VolcengineTTSEngine(api_key="k", voices=bad, endpoint=_ENDPOINT, max_retries=0)

    with pytest.raises(ValueError, match="doubao_9.9"):
        await engine.synthesize(TTSRequest(text="你好", voice="x"))


@pytest.mark.asyncio
@respx.mock
async def test_synthesize_unknown_voice_raises() -> None:
    engine = VolcengineTTSEngine(api_key="k", voices=_VOICES, endpoint=_ENDPOINT, max_retries=0)

    with pytest.raises(ValueError, match="zzz"):
        await engine.synthesize(TTSRequest(text="你好", voice="zzz"))


class _Voice:
    def __init__(self, alias: str, speaker_id: str, engine: str) -> None:
        self.alias, self.speaker_id, self.engine = alias, speaker_id, engine


def test_build_tts_engine_reads_key_from_env_and_maps_voices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOLCENGINE_TTS_API_KEY", "real-key")

    engine = build_tts_engine([_Voice("zizi", "spk", "doubao_2.0")])

    assert isinstance(engine, VolcengineTTSEngine)
    assert engine._api_key == "real-key"
    assert engine._voices == {"zizi": TTSVoiceSpec(speaker_id="spk", engine="doubao_2.0")}


def test_build_tts_engine_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOLCENGINE_TTS_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="VOLCENGINE_TTS_API_KEY"):
        build_tts_engine([])


@pytest.mark.asyncio
async def test_health_check_without_voices_is_false() -> None:
    assert await VolcengineTTSEngine(api_key="k", voices={}).health_check() is False
