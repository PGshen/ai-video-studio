"""`/api/tts/voices`、`/api/tts/preview`（设计 §6.2 设置页「TTS 音色」；计划 M5 T8）。

试听会**真实调用** TTS（可能产生费用），所以：

- 示例文本固定在代码里（`PREVIEW_TEXT`），调用方只能选音色和语速，不能把它当成免费合成接口；
- 结果按（引擎、音色、语速、文本）缓存到 `data/tts-preview/<sha256>.mp3`（数据目录内，不在
  uvicorn 监听范围），同一组合只合成一次，重启后仍然有效；
- 同一个组合的并发请求合并成一次合成（`app.state.tts_preview_inflight`）；
- 失败不缓存；缺 `VOLCENGINE_TTS_API_KEY` 返回 503（指向 `backend/.env`），供应商报错或引擎异常
  返回 502（异常细节只进日志，不进响应）。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from studio.api.deps import get_settings
from studio.config import Settings
from studio.db.repo.settings import SPEECH_RATE_MAX, SPEECH_RATE_MIN
from studio.engines.tts import TTSEngine, TTSRequest, build_tts_engine
from studio.engines.tts.voice_map import DEFAULT_ENGINE, list_voices, voice_aliases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tts"])

PREVIEW_TEXT = "你好，这是一段音色试听。同一句话，换一个声音来说，感觉会很不一样。"
"""固定的试听文本（约 30 个字，费用极小）。"""

_ENGINE_FACTORY: Callable[[], TTSEngine] = build_tts_engine
"""测试里替换成假引擎；默认按环境变量里的 key 建真实引擎。"""


class VoiceOut(BaseModel):
    alias: str
    label: str
    gender: str
    engine: str


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice: str
    speed: float = Field(ge=SPEECH_RATE_MIN, le=SPEECH_RATE_MAX)


@router.get("/tts/voices", response_model=list[VoiceOut])
def list_voices_endpoint() -> list[VoiceOut]:
    return [
        VoiceOut(alias=v.alias, label=v.label, gender=v.gender, engine=v.engine)
        for v in list_voices()
    ]


def _cache_path(data_dir: Path, voice: str, speed: float) -> Path:
    key = hashlib.sha256(
        f"{DEFAULT_ENGINE}|{voice}|{speed:.2f}|{PREVIEW_TEXT}".encode()
    ).hexdigest()
    return data_dir / "tts-preview" / f"{key[:32]}.mp3"


async def _synthesize(voice: str, speed: float) -> bytes:
    try:
        engine = _ENGINE_FACTORY()
    except RuntimeError as exc:  # 缺 key：消息本身就指向 backend/.env，不含密钥
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        result = await engine.synthesize(TTSRequest(text=PREVIEW_TEXT, voice=voice, speed=speed))
    except Exception:
        logger.exception("TTS 试听合成出错")
        raise HTTPException(status_code=502, detail="语音合成出错，请稍后再试") from None
    if not result.success or not result.audio_bytes:
        raise HTTPException(
            status_code=502, detail=f"语音合成失败：{result.error_message or '没有返回音频'}"
        )
    return result.audio_bytes


@router.post("/tts/preview")
async def preview_endpoint(
    body: PreviewRequest, request: Request, settings: Settings = Depends(get_settings)
) -> Response:
    if body.voice not in voice_aliases():
        raise HTTPException(status_code=422, detail=f"音色不可用：{body.voice}")
    speed = round(body.speed, 2)
    path = _cache_path(settings.data_dir, body.voice, speed)
    if path.is_file():
        return Response(content=path.read_bytes(), media_type="audio/mpeg")

    inflight: dict[Path, asyncio.Task[bytes]] | None = getattr(
        request.app.state, "tts_preview_inflight", None
    )
    if inflight is None:
        inflight = request.app.state.tts_preview_inflight = {}
    task = inflight.get(path)
    if task is None:
        task = asyncio.ensure_future(_synthesize(body.voice, speed))
        inflight[path] = task
        task.add_done_callback(lambda _t: inflight.pop(path, None))
    # shield：某个请求的客户端断开时，不要取消其他等着同一次合成的请求。
    audio = await asyncio.shield(task)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(audio)
        tmp.replace(path)
    return Response(content=audio, media_type="audio/mpeg")
