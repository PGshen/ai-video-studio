"""视频画幅约定：宽高比与输出分辨率。

从 `../ai-video/backend/app/video_format.py` 原样迁移。
"""

LANDSCAPE = "landscape"
PORTRAIT = "portrait"

VIDEO_RESOLUTIONS: dict[str, tuple[int, int]] = {
    LANDSCAPE: (1920, 1080),
    PORTRAIT: (1080, 1920),
}


def normalize_aspect_ratio(aspect_ratio: str | None) -> str:
    """返回受支持的宽高比，未知输入保持旧默认值 landscape。"""
    if aspect_ratio == PORTRAIT:
        return PORTRAIT
    return LANDSCAPE


def resolution_for_aspect_ratio(aspect_ratio: str | None) -> tuple[int, int]:
    return VIDEO_RESOLUTIONS[normalize_aspect_ratio(aspect_ratio)]
