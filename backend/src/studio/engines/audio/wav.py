"""只用标准库和 NumPy 的 WAV 读取：PCM 16/24/32 位与 float32，单双声道。

不用标准库 `wave`：它不认 float32。合成脚本的输出格式不受我们控制，所以多认几种，
超限（采样率、大小、时长）和损坏一律用中文 `AudioError` 说清楚。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MIN_SAMPLE_RATE = 22050
MAX_SAMPLE_RATE = 96000
MAX_BYTES = 100 * 1024 * 1024
MAX_SECONDS = 240.0

_PCM = 1
_FLOAT = 3
_EXTENSIBLE = 0xFFFE


class AudioError(ValueError):
    """WAV 缺失、损坏、格式不支持或超限；消息是给 agent 和用户看的中文。"""


@dataclass(frozen=True, slots=True)
class Samples:
    data: np.ndarray
    """float64，单声道形状 `(n,)`，双声道 `(n, 2)`，取值约 [-1, 1]。"""
    sample_rate: int

    @property
    def channels(self) -> int:
        return 1 if self.data.ndim == 1 else int(self.data.shape[1])

    @property
    def duration(self) -> float:
        return len(self.data) / self.sample_rate

    def mono(self) -> np.ndarray:
        return self.data if self.data.ndim == 1 else self.data.mean(axis=1)


def _chunks(raw: bytes) -> dict[str, tuple[int, int]]:
    """chunk 名 → (数据起点, 数据长度)；`data` 长度被截断时取到文件末尾。"""
    found: dict[str, tuple[int, int]] = {}
    position = 12
    while position + 8 <= len(raw):
        name = raw[position : position + 4].decode("ascii", errors="replace")
        (size,) = struct.unpack_from("<I", raw, position + 4)
        start = position + 8
        found.setdefault(name, (start, min(size, len(raw) - start)))
        position = start + size + (size & 1)
    return found


def _decode(payload: bytes, tag: int, bits: int) -> np.ndarray:
    if tag == _FLOAT and bits == 32:
        return np.frombuffer(payload, dtype="<f4").astype(np.float64)
    if tag != _PCM:
        raise AudioError(
            f"不支持的 WAV 编码（格式码 {tag}、{bits} 位）；请输出 PCM 16/24/32 位或 float32"
        )
    if bits == 16:
        return np.frombuffer(payload, dtype="<i2").astype(np.float64) / 32768.0
    if bits == 32:
        return np.frombuffer(payload, dtype="<i4").astype(np.float64) / 2147483648.0
    if bits == 24:
        triples = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
        values = np.where(values >= 1 << 23, values - (1 << 24), values)
        return values.astype(np.float64) / 8388608.0
    raise AudioError(
        f"不支持的 WAV 编码（格式码 {tag}、{bits} 位）；请输出 PCM 16/24/32 位或 float32"
    )


def read_wav(
    path: Path, *, max_bytes: int = MAX_BYTES, max_seconds: float = MAX_SECONDS
) -> Samples:
    if not path.is_file():
        raise AudioError(f"{path.name} 不存在")
    size = path.stat().st_size
    if size > max_bytes:
        raise AudioError(
            f"{path.name} 文件大小超限（{size / 1e6:.1f} MB，上限 {max_bytes / 1e6:.1f} MB）"
        )
    raw = path.read_bytes()
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise AudioError(f"{path.name} 不是有效的 WAV 文件")
    chunks = _chunks(raw)
    if "fmt " not in chunks or "data" not in chunks:
        raise AudioError(f"{path.name} 的 WAV 头不完整（缺少 fmt 或 data）")
    fmt_start, fmt_size = chunks["fmt "]
    if fmt_size < 16:
        raise AudioError(f"{path.name} 的 WAV fmt 块损坏")
    tag, channels, sample_rate, _, _, bits = struct.unpack_from("<HHIIHH", raw, fmt_start)
    if tag == _EXTENSIBLE and fmt_size >= 26:
        (tag,) = struct.unpack_from("<H", raw, fmt_start + 24)
    if channels not in (1, 2):
        raise AudioError(f"只支持单声道或双声道（当前 {channels} 声道）")
    if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
        raise AudioError(
            f"采样率 {sample_rate} Hz 不在支持范围 {MIN_SAMPLE_RATE}–{MAX_SAMPLE_RATE} Hz 内"
        )
    data_start, data_size = chunks["data"]
    width = channels * bits // 8
    usable = data_size - data_size % width if width else 0
    if usable <= 0:
        raise AudioError(f"{path.name} 里没有音频数据")
    duration = usable / width / sample_rate
    if duration > max_seconds:
        raise AudioError(f"音频时长 {duration:.1f} 秒超过上限 {max_seconds:.0f} 秒")
    values = _decode(raw[data_start : data_start + usable], tag, bits)
    if not np.isfinite(values).all():
        raise AudioError(f"{path.name} 含 NaN 或无穷大的样本；检查合成脚本里的除零与 log(0)")
    data = values if channels == 1 else values.reshape(-1, 2)
    return Samples(data=data, sample_rate=sample_rate)
