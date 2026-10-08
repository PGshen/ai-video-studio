"""风格截图：图片规范化、文件名规则、目录列出（计划 style-screenshots T1，ADR 0022）。

截图存在风格目录的 `screenshots/` 下，文件名 `<三位序号>-<内容 sha256 前 12 位>.webp`：按文件名
排序就是显示顺序，第一张是封面；名字里带内容哈希，浏览器可以放心缓存。纯函数加少量只读的目录扫描，
没有数据库依赖。
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Final

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SCREENSHOTS: Final = 12
MAX_UPLOAD_BYTES: Final = 10 * 1024 * 1024
MAX_PIXELS: Final = 50_000_000
MAX_EDGE: Final = 1920
_WEBP_QUALITY: Final = 85
_FORMATS: Final = ("PNG", "JPEG", "WEBP")
_NAME = re.compile(r"^\d{3}-[0-9a-f]{12}\.webp$")
_IGNORED: Final = {".DS_Store"}


class ScreenshotError(ValueError):
    """上传的不是可用的截图（API 映射为 422）；消息是中文。"""


def normalize_image(data: bytes) -> bytes:
    """把上传的 PNG/JPEG/WebP 转成长边不超过 `MAX_EDGE` 的 WebP。

    格式以 Pillow 识别的为准，不信任扩展名；像素数在解码之前用图片头检查，防止解压炸弹。"""
    if not data:
        raise ScreenshotError("没有收到文件，或者文件是空的")
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in _FORMATS:
            raise ScreenshotError("只支持 PNG、JPEG、WebP 图片")
        if image.width * image.height > MAX_PIXELS:
            raise ScreenshotError(f"图片像素太多（上限 {MAX_PIXELS // 1_000_000} 百万像素）")
        image.load()
    except ScreenshotError:
        raise
    except Image.DecompressionBombError as exc:  # Pillow 自己的保护：远超默认上限时在打开时就抛
        raise ScreenshotError(f"图片像素太多（上限 {MAX_PIXELS // 1_000_000} 百万像素）") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ScreenshotError("不是有效的图片文件") from exc
    image.seek(0)
    oriented = ImageOps.exif_transpose(image)
    oriented.thumbnail((MAX_EDGE, MAX_EDGE))
    if oriented.mode not in ("RGB", "RGBA"):
        oriented = oriented.convert("RGBA" if "transparency" in oriented.info else "RGB")
    buffer = io.BytesIO()
    oriented.save(buffer, format="WEBP", quality=_WEBP_QUALITY)
    return buffer.getvalue()


def is_screenshot_name(name: str) -> bool:
    return _NAME.match(name) is not None


def screenshot_name(index: int, data: bytes) -> str:
    """第 `index`（从 0 开始）张截图的文件名。"""
    return f"{index + 1:03d}-{hashlib.sha256(data).hexdigest()[:12]}.webp"


def list_screenshots(root: Path) -> tuple[list[str], list[str]]:
    """`root`（`screenshots/` 目录）下合法的截图文件名（已排序）和发现的问题；目录不存在时都为空。

    符号链接、子目录、名字不合法的文件、数量超过 `MAX_SCREENSHOTS` 都记为问题（不读文件内容）。"""
    if not root.is_dir() or root.is_symlink():
        return [], []
    names: list[str] = []
    problems: list[str] = []
    for entry in sorted(root.iterdir()):
        if entry.name in _IGNORED:
            continue
        label = f"screenshots/{entry.name}"
        if entry.is_symlink() or not entry.is_file():
            problems.append(f"不允许符号链接或子目录：{label}")
        elif not is_screenshot_name(entry.name):
            problems.append(f"截图文件名不合法：{label}")
        else:
            names.append(entry.name)
    if len(names) > MAX_SCREENSHOTS:
        problems.append(f"截图最多 {MAX_SCREENSHOTS} 张，现在有 {len(names)} 张")
    return names, problems


def renumbered(names: list[str]) -> list[tuple[str, str]]:
    """按给定顺序重排序号：返回（旧名，新名）列表，哈希部分保留。"""
    return [(name, f"{index + 1:03d}-{name[4:]}") for index, name in enumerate(names)]
