"""`/api/tts/voices`、`/api/tts/preview`（计划 M5 T8）。

试听会真实调用 TTS（可能产生费用）：结果按（引擎、音色、语速、文本）缓存到
`data/tts-preview/`，同一组合只合成一次；并发的相同请求合并成一次合成。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from studio.api import tts as tts_module
from studio.engines.tts.base import TTSRequest, TTSResult
from studio.engines.tts.voice_map import voice_aliases

from .conftest import ApiEnv, assert_detail

FAKE_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00fake-mp3-bytes"


class FakeEngine:
    """记录每次 `synthesize` 调用的替身引擎。"""

    engine_name = "fake"

    def __init__(self, *, delay: float = 0.0, result: TTSResult | None = None) -> None:
        self.requests: list[TTSRequest] = []
        self._delay = delay
        self._result = result

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        self.requests.append(request)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._result is not None:
            return self._result
        return TTSResult(
            success=True,
            output_path=None,
            duration_seconds=1.0,
            error_message=None,
            audio_bytes=FAKE_MP3,
        )

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    fake = FakeEngine()
    monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda: fake)
    return fake


async def _preview(api_env: ApiEnv, **body: Any) -> Any:
    payload = {"voice": "zizi", "speed": 1.0, **body}
    return await api_env.client.post("/api/tts/preview", json=payload)


class TestVoices:
    async def test_lists_supported_voices_with_labels(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/tts/voices")

        assert response.status_code == 200
        body = response.json()
        assert [v["alias"] for v in body] == voice_aliases()
        zizi = next(v for v in body if v["alias"] == "zizi")
        assert zizi == {
            "alias": "zizi",
            "label": "清澈梓梓",
            "gender": "female",
            "engine": "doubao_2.0",
        }


class TestPreview:
    async def test_returns_the_synthesized_audio(self, api_env: ApiEnv, engine: FakeEngine) -> None:
        response = await _preview(api_env, voice="xiaohe", speed=1.2)

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "audio/mpeg"
        assert response.content == FAKE_MP3
        assert len(engine.requests) == 1
        request = engine.requests[0]
        assert (request.voice, request.speed) == ("xiaohe", 1.2)
        assert request.text == tts_module.PREVIEW_TEXT

    async def test_second_identical_request_is_served_from_the_cache(
        self, api_env: ApiEnv, engine: FakeEngine
    ) -> None:
        first = await _preview(api_env)
        second = await _preview(api_env)

        assert first.content == second.content == FAKE_MP3
        assert len(engine.requests) == 1
        cache_dir = Path(api_env.data_dir) / "tts-preview"
        assert [p.suffix for p in cache_dir.iterdir()] == [".mp3"]

    async def test_a_different_voice_or_speed_is_synthesized_again(
        self, api_env: ApiEnv, engine: FakeEngine
    ) -> None:
        await _preview(api_env, voice="zizi", speed=1.0)
        await _preview(api_env, voice="zizi", speed=1.5)
        await _preview(api_env, voice="xiaohe", speed=1.0)

        assert len(engine.requests) == 3

    async def test_speed_is_normalized_so_float_noise_does_not_defeat_the_cache(
        self, api_env: ApiEnv, engine: FakeEngine
    ) -> None:
        await _preview(api_env, speed=1.1)
        await _preview(api_env, speed=1.1000000001)

        assert len(engine.requests) == 1

    async def test_concurrent_identical_requests_are_merged_into_one_synthesis(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slow = FakeEngine(delay=0.1)
        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda: slow)

        responses = await asyncio.gather(*[_preview(api_env) for _ in range(6)])

        assert all(r.status_code == 200 and r.content == FAKE_MP3 for r in responses)
        assert len(slow.requests) == 1

    async def test_cache_survives_a_restart(
        self, api_env: ApiEnv, engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _preview(api_env)
        fresh = FakeEngine()
        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda: fresh)
        api_env.app.state.tts_preview_inflight = {}

        response = await _preview(api_env)

        assert response.content == FAKE_MP3
        assert fresh.requests == []

    async def test_a_failed_synthesis_is_502_and_not_cached(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failing = FakeEngine(
            result=TTSResult(
                success=False,
                output_path=None,
                duration_seconds=None,
                error_message="供应商返回 429",
                audio_bytes=b"",
            )
        )
        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda: failing)

        first = await _preview(api_env)
        second = await _preview(api_env)

        assert first.status_code == second.status_code == 502
        assert "供应商返回 429" in assert_detail(first)
        assert len(failing.requests) == 2
        cache_dir = Path(api_env.data_dir) / "tts-preview"
        assert not cache_dir.exists() or list(cache_dir.iterdir()) == []

    async def test_empty_audio_is_502(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = FakeEngine(
            result=TTSResult(
                success=True,
                output_path=None,
                duration_seconds=0.0,
                error_message=None,
                audio_bytes=b"",
            )
        )
        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda: empty)

        response = await _preview(api_env)

        assert response.status_code == 502

    async def test_an_engine_exception_is_502_without_leaking_details(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Boom(FakeEngine):
            async def synthesize(self, request: TTSRequest) -> TTSResult:
                raise RuntimeError("Authorization: Bearer sk-secret-token")

        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda: Boom())

        response = await _preview(api_env)

        assert response.status_code == 502
        assert "sk-secret-token" not in response.text

    async def test_missing_api_key_is_503_pointing_at_the_env_file(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_key() -> FakeEngine:
            raise RuntimeError("环境变量 VOLCENGINE_TTS_API_KEY 未设置，请在 backend/.env 中配置。")

        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", no_key)

        response = await _preview(api_env)

        assert response.status_code == 503
        assert "VOLCENGINE_TTS_API_KEY" in assert_detail(response)
        assert ".env" in assert_detail(response)

    @pytest.mark.parametrize("speed", [0.49, 2.01, 0, -1, 100])
    async def test_speed_out_of_range_is_422(
        self, api_env: ApiEnv, engine: FakeEngine, speed: float
    ) -> None:
        response = await _preview(api_env, speed=speed)

        assert response.status_code == 422
        assert engine.requests == []

    async def test_speed_bounds_are_inclusive(self, api_env: ApiEnv, engine: FakeEngine) -> None:
        assert (await _preview(api_env, speed=0.5)).status_code == 200
        assert (await _preview(api_env, speed=2.0)).status_code == 200

    async def test_unknown_voice_is_422(self, api_env: ApiEnv, engine: FakeEngine) -> None:
        response = await _preview(api_env, voice="not-a-voice")

        assert response.status_code == 422
        assert "音色" in assert_detail(response)
        assert engine.requests == []

    async def test_the_caller_cannot_choose_the_text(
        self, api_env: ApiEnv, engine: FakeEngine
    ) -> None:
        response = await _preview(api_env, text="任意文本")

        assert response.status_code == 422
        assert engine.requests == []

    async def test_missing_fields_are_422(self, api_env: ApiEnv, engine: FakeEngine) -> None:
        response = await api_env.client.post("/api/tts/preview", json={"voice": "zizi"})

        assert response.status_code == 422
