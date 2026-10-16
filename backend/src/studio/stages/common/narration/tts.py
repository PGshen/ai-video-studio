"""`tts` 工具：完全自由阶段的通用配音（open-mode 设计 §4.2）。

不读写叙事格式：一段文字 → 一个 mp3，写到 agent 指定的工作区路径。密钥在后端，agent 在 Bash 里
做不了这件事，所以这是完全自由阶段唯一的自建工具。工具描述就是它的完整说明，不进系统提示词。

`_ENGINE_FACTORY` 是模块级的可替换"缝"（同 `synthesize_tts`），测试换成假引擎。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence

from pydantic import BaseModel, Field

from studio.agent.tools import ToolContext, ToolResult, ToolSpec
from studio.db.repo.settings import SPEECH_RATE_MAX, SPEECH_RATE_MIN
from studio.db.repo.voices import VoiceValue, list_voices
from studio.engines.tts import TTSEngine, TTSRequest, build_tts_engine
from studio.stages.common.narration.synthesize_tts import project_voice_and_speed
from studio.stages.common.open_scope import OPEN_WRITE_SCOPE
from studio.workspace import files
from studio.workspace.scope import is_writable

_ENGINE_FACTORY: Callable[[Sequence[VoiceValue]], TTSEngine] = build_tts_engine

MAX_TEXT_CHARS = 2000
"""单次配音的文字上限：豆包单次请求能稳定处理的长度，更长的请分段。"""


class TtsArgs(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    out_path: str
    voice: str | None = None
    speed: float | None = Field(default=None, ge=SPEECH_RATE_MIN, le=SPEECH_RATE_MAX)


def _target(out_path: str) -> str | None:
    """校验通过时返回规范化的相对路径，否则返回 `None`。"""
    try:
        relpath = files.check_model_path(out_path).as_posix()
    except files.ScopeError:
        return None
    if not relpath.endswith(".mp3") or not is_writable(OPEN_WRITE_SCOPE, relpath):
        return None
    return relpath


async def _handler(ctx: ToolContext, args: TtsArgs) -> ToolResult:
    text = args.text.strip()
    if not text:
        return ToolResult(text="text 不能为空。", is_error=True)
    relpath = _target(args.out_path)
    if relpath is None:
        return ToolResult(
            text=(
                f"不能写到 {args.out_path!r}：out_path 必须是工作区内的相对路径、以 .mp3 结尾，"
                "且不在 uploads/、upstream/、output/、.cache/ 下。"
            ),
            is_error=True,
        )
    default_voice, default_speed = project_voice_and_speed(ctx)
    voice = args.voice or default_voice
    speed = args.speed if args.speed is not None else default_speed
    engine = _ENGINE_FACTORY(list_voices(ctx.engine) if ctx.engine is not None else [])
    result = await engine.synthesize(TTSRequest(text=text, voice=voice, speed=speed))
    if not result.success:
        return ToolResult(text=f"配音失败：{result.error_message or '未知错误'}", is_error=True)

    path = files.safe_path(ctx.workdir, relpath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result.audio_bytes)
    ctx.record_tool_write(relpath, hashlib.sha256(result.audio_bytes).hexdigest())
    duration = result.duration_seconds or 0.0
    return ToolResult(text=f"已写入 {relpath}（时长 {duration:.2f}s，音色 {voice}，语速 {speed}）")


TTS_TOOL = ToolSpec(
    name="tts",
    description=(
        "把一段文字合成为语音（mp3），写到工作区里 out_path 指定的位置（目录会自动创建）。"
        f"text 最多 {MAX_TEXT_CHARS} 字，更长的请分段多次调用；voice、speed 不填时用项目设置的"
        "音色和语速。返回写入路径和音频时长。"
    ),
    input_model=TtsArgs,
    stages={"open"},
    handler=_handler,
)
