"""返回给模型的图片的大小控制（阶段工具共用）。

Claude SDK 单条 JSON 消息不能超过 1 MiB（3A 真实模型冒烟实测踩到：超限整轮失败，追加轮又带上这条
历史所以再失败）。工具结果里的图片按 base64 内联，所以要压成 JPEG 并限制字节数；要给人看的原图
另存为文件，不走这里。
"""

from __future__ import annotations

import io

from PIL import Image

DEFAULT_LIMIT_BYTES = 400_000
"""一张图的默认上限（base64 之后再大三分之一）。"""
TOTAL_LIMIT_BYTES = 600_000
"""同一条工具结果里所有图片的字节总预算。"""
_MIN_LIMIT_BYTES = 40_000


def compress_png(png: bytes, limit: int = DEFAULT_LIMIT_BYTES) -> bytes:
    """PNG → JPEG：质量 85/70/55/40 逐级下降，仍超限就缩小到 0.8 倍再来。"""
    image = Image.open(io.BytesIO(png)).convert("RGB")
    while True:
        for quality in (85, 70, 55, 40):
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            if buffer.tell() <= limit:
                return buffer.getvalue()
        image = image.resize((max(1, int(image.width * 0.8)), max(1, int(image.height * 0.8))))


def limit_for(count: int) -> int:
    """`count` 张图共用 `TOTAL_LIMIT_BYTES` 时每张的上限（至少留一点，单张不超过默认上限）。"""
    if count <= 1:
        return DEFAULT_LIMIT_BYTES
    return min(DEFAULT_LIMIT_BYTES, max(_MIN_LIMIT_BYTES, TOTAL_LIMIT_BYTES // count))
