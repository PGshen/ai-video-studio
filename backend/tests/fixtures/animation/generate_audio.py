"""生成本目录 `audio/*.wav` 的脚本（M2 T4，决策记录 D3）。

叙事阶段的真实 TTS 是 M3 范围，本 fixture 不依赖任何外部 API 或付费调用：
用标准库 `wave`/`math` 合成带淡入淡出的正弦波（纯静音在 `make dev` 手动
走查时听起来像坏文件，加一点波形更容易分辨"这是有效的占位音频"）。

不是测试代码，`make check` 不会执行它；只在需要重新生成或调整 fixture 音频
时手动运行：

    cd backend && uv run python tests/fixtures/animation/generate_audio.py

运行后需要同步更新 `timing.json` 里对应镜头的 `audio_hash`（脚本会把新的
sha256 打印出来）与 `duration_seconds`（如果改了时长）。
"""

from __future__ import annotations

import hashlib
import math
import wave
from pathlib import Path

_FRAME_RATE = 24000
_OUT_DIR = Path(__file__).parent / "audio"

# (文件名, 时长秒, 频率 Hz) —— 时长 ≥ 1.0s 是 Manim 时期的约束（已下线，ADR 0027；
# manim `add_sound()` 会给音轨套一层至少 1 秒的静音底轨，短于 1 秒的声明
# 时长会被这个下限干扰，破坏 `render_preview` 的起始偏移计算）。
_SCENES: tuple[tuple[str, float, float], ...] = (
    ("s-hook.wav", 1.4, 440.0),
    ("s-explain.wav", 1.6, 523.25),
)


def _write_sine_wav(path: Path, duration_seconds: float, frequency_hz: float) -> bytes:
    n_frames = int(_FRAME_RATE * duration_seconds)
    amplitude = 12000
    frames = bytearray()
    for i in range(n_frames):
        t = i / _FRAME_RATE
        fade = max(0.0, min(1.0, t / 0.05, (duration_seconds - t) / 0.05))
        sample = int(amplitude * fade * math.sin(2 * math.pi * frequency_hz * t))
        frames += sample.to_bytes(2, byteorder="little", signed=True)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(_FRAME_RATE)
        wav_file.writeframes(bytes(frames))
    # sha256 要覆盖磁盘上的完整文件（含 WAV 头），因为 `timing.json` 里的
    # `audio_hash` 描述的是 `seed_animation_project` 实际写进工作区、消费者
    # 实际读到的文件内容，不是合成用的原始 PCM 采样。
    return path.read_bytes()


def main() -> None:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, duration, frequency in _SCENES:
        raw = _write_sine_wav(_OUT_DIR / filename, duration, frequency)
        digest = hashlib.sha256(raw).hexdigest()
        print(f"{filename}: duration={duration}s sha256={digest} bytes={len(raw)}")


if __name__ == "__main__":
    main()
