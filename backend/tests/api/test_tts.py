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
    monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda _v: fake)
    return fake


async def _preview(api_env: ApiEnv, **body: Any) -> Any:
    payload = {"voice": "zizi", "speed": 1.0, **body}
    return await api_env.client.post("/api/tts/preview", json=payload)


SEED_ALIASES = ["sisi", "xiaozhupeiqi", "xiaoxinjiejie", "zizi", "yunzhou", "xiaohe"]
NEW_VOICE = {
    "alias": "newone",
    "label": "新音色",
    "gender": "male",
    "speaker_id": "zh_male_new_uranus_bigtts",
    "engine": "doubao_2.0",
}


class TestVoices:
    async def test_lists_all_voices_with_both_versions(self, api_env: ApiEnv) -> None:
        response = await api_env.client.get("/api/tts/voices")

        assert response.status_code == 200
        body = response.json()
        assert [v["alias"] for v in body] == SEED_ALIASES
        zizi = next(v for v in body if v["alias"] == "zizi")
        assert zizi == {
            "alias": "zizi",
            "label": "清澈梓梓",
            "gender": "female",
            "speaker_id": "zh_female_qingchezizi_uranus_bigtts",
            "engine": "doubao_2.0",
        }
        assert next(v for v in body if v["alias"] == "sisi")["engine"] == "doubao_1.0"

    async def test_a_new_voice_is_listed_usable_for_projects_defaults_and_preview(
        self, api_env: ApiEnv, engine: FakeEngine
    ) -> None:
        created = await api_env.client.post("/api/tts/voices", json=NEW_VOICE)
        assert created.status_code == 201, created.text
        assert created.json() == NEW_VOICE

        listed = (await api_env.client.get("/api/tts/voices")).json()
        assert listed[-1]["alias"] == "newone"
        project = await api_env.create_project()
        patched = await api_env.client.patch(
            f"/api/projects/{project['id']}/settings", json={"voice": "newone"}
        )
        assert patched.status_code == 200, patched.text
        default = await api_env.client.patch(
            "/api/settings", json={"tts_default": {"voice": "newone"}}
        )
        assert default.status_code == 200, default.text
        preview = await _preview(api_env, voice="newone")
        assert preview.status_code == 200
        assert engine.requests[-1].voice == "newone"

    async def test_preview_hands_the_engine_only_the_previewed_voice(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Any] = []

        def factory(voices: Any) -> FakeEngine:
            seen.extend(voices)
            return FakeEngine()

        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", factory)

        await _preview(api_env, voice="sisi")

        assert [(v.alias, v.engine) for v in seen] == [("sisi", "doubao_1.0")]

    async def test_duplicate_alias_is_409(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post("/api/tts/voices", json={**NEW_VOICE, "alias": "zizi"})

        assert response.status_code == 409
        assert "zizi" in assert_detail(response)

    @pytest.mark.parametrize(
        "over",
        [
            {"alias": "Bad Alias"},
            {"speaker_id": ""},
            {"engine": "doubao_3.0"},
            {"gender": "other"},
            {"label": " "},
        ],
    )
    async def test_invalid_fields_are_422(self, api_env: ApiEnv, over: dict[str, str]) -> None:
        response = await api_env.client.post("/api/tts/voices", json={**NEW_VOICE, **over})

        assert response.status_code == 422
        assert len((await api_env.client.get("/api/tts/voices")).json()) == len(SEED_ALIASES)

    async def test_unknown_fields_are_422(self, api_env: ApiEnv) -> None:
        response = await api_env.client.post("/api/tts/voices", json={**NEW_VOICE, "x": 1})

        assert response.status_code == 422

    async def test_delete_removes_the_voice(self, api_env: ApiEnv) -> None:
        response = await api_env.client.delete("/api/tts/voices/xiaohe")

        assert response.status_code == 204
        aliases = [v["alias"] for v in (await api_env.client.get("/api/tts/voices")).json()]
        assert "xiaohe" not in aliases

    async def test_delete_unknown_is_404(self, api_env: ApiEnv) -> None:
        assert (await api_env.client.delete("/api/tts/voices/nope")).status_code == 404

    async def test_delete_a_voice_used_by_a_project_is_409(self, api_env: ApiEnv) -> None:
        project = await api_env.create_project()
        await api_env.client.patch(
            f"/api/projects/{project['id']}/settings", json={"voice": "yunzhou"}
        )

        response = await api_env.client.delete("/api/tts/voices/yunzhou")

        assert response.status_code == 409
        assert "1 个项目" in assert_detail(response)

    async def test_delete_the_default_voice_is_409(self, api_env: ApiEnv) -> None:
        response = await api_env.client.delete("/api/tts/voices/zizi")

        assert response.status_code == 409
        assert "默认" in assert_detail(response)

    async def test_a_deleted_voice_is_no_longer_accepted(self, api_env: ApiEnv) -> None:
        await api_env.client.delete("/api/tts/voices/xiaohe")
        project = await api_env.create_project()

        patched = await api_env.client.patch(
            f"/api/projects/{project['id']}/settings", json={"voice": "xiaohe"}
        )
        default = await api_env.client.patch(
            "/api/settings", json={"tts_default": {"voice": "xiaohe"}}
        )
        preview = await _preview(api_env, voice="xiaohe")

        assert patched.status_code == default.status_code == preview.status_code == 422

    async def test_preview_cache_is_not_shared_after_the_speaker_changes(
        self, api_env: ApiEnv, engine: FakeEngine
    ) -> None:
        await api_env.client.post("/api/tts/voices", json=NEW_VOICE)
        await _preview(api_env, voice="newone")
        await api_env.client.delete("/api/tts/voices/newone")
        await api_env.client.post(
            "/api/tts/voices", json={**NEW_VOICE, "speaker_id": "another_speaker"}
        )

        await _preview(api_env, voice="newone")

        assert len(engine.requests) == 2


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
        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda _v: slow)

        responses = await asyncio.gather(*[_preview(api_env) for _ in range(6)])

        assert all(r.status_code == 200 and r.content == FAKE_MP3 for r in responses)
        assert len(slow.requests) == 1

    async def test_cache_survives_a_restart(
        self, api_env: ApiEnv, engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _preview(api_env)
        fresh = FakeEngine()
        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda _v: fresh)
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
        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda _v: failing)

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
        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda _v: empty)

        response = await _preview(api_env)

        assert response.status_code == 502

    async def test_an_engine_exception_is_502_without_leaking_details(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Boom(FakeEngine):
            async def synthesize(self, request: TTSRequest) -> TTSResult:
                raise RuntimeError("Authorization: Bearer sk-secret-token")

        monkeypatch.setattr(tts_module, "_ENGINE_FACTORY", lambda _v: Boom())

        response = await _preview(api_env)

        assert response.status_code == 502
        assert "sk-secret-token" not in response.text

    async def test_missing_api_key_is_503_pointing_at_the_env_file(
        self, api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_key(_voices: object) -> FakeEngine:
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
