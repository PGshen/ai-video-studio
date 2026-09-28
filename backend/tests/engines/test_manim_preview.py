import wave
from pathlib import Path

import pytest

from studio.engines.render.base import PreviewRequest, SceneAudio, SceneInput
from studio.engines.render.manim import ManimRenderEngine


def _write_silent_wav(path: Path, duration_seconds: float) -> None:
    frame_rate = 8000
    n_frames = int(frame_rate * duration_seconds)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(b"\x00\x00" * n_frames)


def _two_scene_request(tmp_path: Path) -> PreviewRequest:
    # manim 的 add_sound() 会给整段视频套一层至少 1 秒的静音底轨（docs/references/
    # manim.md），声明的镜头时长要 >= 1.0s 才不会被这个下限干扰起始偏移的计算。
    audio_path = tmp_path / "silence.wav"
    _write_silent_wav(audio_path, duration_seconds=1.0)

    scenes = [
        SceneInput(
            scene_index=0,
            narration="",
            description="镜头0",
            code="self.add(Dot())",
            audio=SceneAudio(scene_index=0, audio_path=str(audio_path), duration_seconds=1.0),
        ),
        SceneInput(
            scene_index=1,
            narration="",
            description="镜头1",
            code="self.add(Square())",
            audio=SceneAudio(scene_index=1, audio_path=str(audio_path), duration_seconds=1.0),
        ),
    ]
    return PreviewRequest(
        scenes=scenes,
        target_scene_index=1,
        beat_end_times=[0.5, 1.0],
        audio_duration_seconds=1.0,
    )


@pytest.mark.slow
async def test_render_preview_returns_one_keyframe_per_beat(tmp_path):
    request = _two_scene_request(tmp_path)

    result = await ManimRenderEngine().render_preview(request)

    assert result.success is True, result.error_message
    assert len(result.keyframes) == len(request.beat_end_times)
    assert [kf.beat_index for kf in result.keyframes] == [0, 1]
    assert all(len(kf.png_bytes) > 0 for kf in result.keyframes)
    assert result.render_duration_seconds is not None
    assert result.render_duration_seconds >= 0


@pytest.mark.slow
async def test_render_preview_computes_duration_deviation(tmp_path):
    request = _two_scene_request(tmp_path)

    result = await ManimRenderEngine().render_preview(request)

    assert result.success is True, result.error_message
    assert result.duration_deviation_seconds is not None
    # 目标镜头的音频时长是 0.4s；渲染帧对齐到 fps 会有量化误差，容忍 0.3s 内。
    assert abs(result.duration_deviation_seconds) < 0.3


@pytest.mark.slow
async def test_render_preview_skips_deviation_without_audio_duration(tmp_path):
    request = _two_scene_request(tmp_path)
    request.audio_duration_seconds = None

    result = await ManimRenderEngine().render_preview(request)

    assert result.success is True, result.error_message
    assert result.duration_deviation_seconds is None


async def test_render_preview_times_out_without_waiting_120_seconds(tmp_path):
    request = _two_scene_request(tmp_path)

    result = await ManimRenderEngine().render_preview(request, timeout_seconds=0.001)

    assert result.success is False
    assert result.error_message == "预览渲染超时"
    assert result.keyframes == []
