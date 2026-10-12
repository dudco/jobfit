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


INK_THRESHOLD = 1.0  # 행의 '잉크량'(가로 이웃 픽셀 밝기 차의 평균)이 이 값 이하면 여백 행


def fit_width(img: Image.Image, max_width: int) -> Image.Image:
    if img.width <= max_width:
        return img
    return img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)


def row_ink(img: Image.Image) -> list[float]:
    """행별 잉크량 — 가로로 이웃한 픽셀 사이 밝기 차의 평균.

    글자 줄은 밝기가 자주 바뀌어 값이 크고, 단색 면·배경·좌우 테두리는 거의 0이다.
    (행 표준편차는 '흰 본문 + 회색 테두리'처럼 글자 없는 행도 크게 나와 여백을 못 찾는다)
    """
    gray = img.convert("L")
    diff = ImageChops.difference(gray, ImageChops.offset(gray, 1, 0))
    return [ImageStat.Stat(diff.crop((0, y, diff.width, y + 1))).mean[0] for y in range(diff.height)]


def _widest_gap_center(ink: list[float], lo: int, hi: int, threshold: float):
    """[lo, hi) 구간에서 가장 긴 여백 띠의 가운데 행. 여백이 없으면 None."""
    best = None
    run_start = None
    for y in range(lo, hi + 1):
        blank = y < hi and ink[y] <= threshold
        if blank and run_start is None:
            run_start = y
        elif not blank and run_start is not None:
            length = y - run_start
            if best is None or length > best[0]:
                best = (length, run_start + length // 2)
            run_start = None
    return None if best is None else best[1]


def _least_ink_row(ink: list[float], lo: int, hi: int) -> int:
    """[lo, hi] 구간에서 잉크가 가장 적은 행. 같으면 아래쪽(조각을 크게)."""
    return min(range(lo, hi + 1), key=lambda y: (ink[y] if y < len(ink) else 0.0, -y))


def plan_slices(ink: list[float], *, target_height: int, search: int = 300, overlap: int = 100,
                threshold: float = INK_THRESHOLD) -> list[tuple[int, int]]:
    """자를 구간 [(top, bottom), …].

    목표 높이 직전 search 구간에서 가장 긴 여백 띠의 가운데를 자른다. 여백이 없으면(표·그림이 이어짐)
    잉크가 가장 적은 행에서 자르고 overlap만큼 겹친다. target_height=0이면 자르지 않는다.
    """
    height = len(ink)
    if target_height <= 0 or height <= target_height:
        return [(0, height)]
    if overlap >= target_height:
        raise ValueError("overlap은 target_height보다 작아야 합니다")
    search = min(search, target_height - 1)
    slices: list[tuple[int, int]] = []
    top = 0
    while top < height:
        if height - top <= target_height:
            slices.append((top, height))
            break
        limit = top + target_height
        lo = max(top + overlap + 1, limit - search)
        cut = _widest_gap_center(ink, lo, limit, threshold)
        if cut is not None:
            slices.append((top, cut))
            top = cut
        else:
            cut = _least_ink_row(ink, lo, limit)
            slices.append((top, cut))
            top = cut - overlap
    return slices


def slice_image(img: Image.Image, *, max_width: int = 1000, target_height: int = 1200, search: int = 300,
                overlap: int = 100, threshold: float = INK_THRESHOLD) -> list[Image.Image]:
    """정규화 → 폭 맞춤 → 여백 기반 분할 → 글자가 없는 조각 제거."""
    img = fit_width(normalize(img), max_width)
    ink = row_ink(img)
    pieces = []
    for top, bottom in plan_slices(ink, target_height=target_height, search=search, overlap=overlap,
                                   threshold=threshold):
        if max(ink[top:bottom], default=0.0) > threshold:
            pieces.append(img.crop((0, top, img.width, bottom)))
    return pieces
