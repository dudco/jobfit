"""공고 이미지 전처리 — 정규화와 여백 기반 분할 (ADR-0012).

LLM을 쓰지 않는 결정적인 이미지 처리 코드다.
"""
from __future__ import annotations

from PIL import Image, ImageChops, ImageStat


def normalize(img: Image.Image) -> Image.Image:
    """RGB로 바꾼다. 투명 영역은 흰 배경에 합성하고, 애니메이션은 첫 프레임을 쓴다.

    투명 PNG를 그냥 RGB로 바꾸면 투명 영역이 검정이 되어 검은 글자가 사라진다.
    """
    if getattr(img, "is_animated", False):
        img.seek(0)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")
