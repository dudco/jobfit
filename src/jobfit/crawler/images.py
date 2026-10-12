"""내려받은 바이트가 공고 본문 이미지로 쓸 만한지 검사하고 메타데이터를 읽는다.
원본 바이트는 바꾸지 않는다 (ADR-0005)."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from PIL import Image, UnidentifiedImageError

MIN_LONG_SIDE = 200  # 긴 변이 이보다 작으면 아이콘·장식으로 본다
EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}


@dataclass(frozen=True)
class ImageInfo:
    format: str
    width: int
    height: int


def inspect_image(data: bytes, *, min_long_side: int = MIN_LONG_SIDE) -> Optional[ImageInfo]:
    """본문 이미지로 쓸 수 있으면 메타데이터, 아니면 None (디코딩 불가·너무 작음)."""
    try:
        with Image.open(BytesIO(data)) as im:
            info = ImageInfo(format=im.format or "UNKNOWN", width=im.width, height=im.height)
    except (UnidentifiedImageError, OSError):
        return None
    return info if max(info.width, info.height) >= min_long_side else None


def extension(info: ImageInfo) -> str:
    return EXTENSIONS.get(info.format, ".bin")
