from PIL import Image, ImageDraw, ImageStat

from preprocessing.images import normalize


def test_transparent_background_becomes_white():
    img = Image.new("RGBA", (100, 50), (0, 0, 0, 0))                       # 완전 투명
    ImageDraw.Draw(img).rectangle([10, 10, 90, 20], fill=(0, 0, 0, 255))  # 검은 글자
    out = normalize(img)
    assert out.mode == "RGB"
    assert out.getpixel((2, 2)) == (255, 255, 255)
    assert out.getpixel((50, 15)) == (0, 0, 0)


def test_animated_gif_uses_first_frame(tmp_path):
    frames = [Image.new("RGB", (40, 40), color) for color in ("red", "blue")]
    path = tmp_path / "a.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:])
    with Image.open(path) as im:
        im.seek(1)                       # 다른 프레임에 가 있어도
        out = normalize(im)
    assert out.getpixel((5, 5)) == (255, 0, 0)


import pytest

from preprocessing.images import INK_THRESHOLD, plan_slices, row_ink, slice_image


def text_lines(width, height, rows, background="white", card=None):
    """rows=[(y0, y1), …] 위치에 글자 줄처럼 끊긴 검은 막대를 그린다.
    card=(x0, x1)이면 회색 배경 위 흰 카드 안에만 그린다 (실제 공고 포스터의 좌우 테두리 재현)."""
    img = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(img)
    x0, x1 = card or (0, width)
    if card:
        draw.rectangle([x0, 0, x1, height], fill="white")
    for y0, y1 in rows:
        for x in range(x0 + 10, x1 - 10, 12):
            draw.rectangle([x, y0, x + 7, y1], fill="black")
    return img


def boundary_rows_are_blank(piece):
    ink = row_ink(piece)
    return ink[0] <= INK_THRESHOLD and ink[-1] <= INK_THRESHOLD


def test_cuts_in_the_widest_gap_before_target_height():
    ink = [50.0] * 1000
    for y in range(700, 760):
        ink[y] = 0.0                             # 넓은 여백 (가운데 730)
    for y in range(900, 905):
        ink[y] = 0.0                             # 좁은 여백
    assert plan_slices(ink, target_height=950, search=300, overlap=50) == [(0, 730), (730, 1000)]


def test_without_gap_cuts_at_least_ink_row_and_overlaps():
    ink = [50.0] * 2500
    ink[850] = 10.0                              # 표 안에서 글자가 가장 적은 행
    assert plan_slices(ink, target_height=1000, search=300, overlap=100) == [
        (0, 850), (750, 1750), (1650, 2500),
    ]


def test_short_image_or_zero_target_is_a_single_slice():
    assert plan_slices([50.0] * 500, target_height=1200, search=300, overlap=100) == [(0, 500)]
    assert plan_slices([50.0] * 5000, target_height=0, search=300, overlap=100) == [(0, 5000)]


def test_rejects_overlap_not_smaller_than_target():
    with pytest.raises(ValueError):
        plan_slices([50.0] * 3000, target_height=100, search=50, overlap=100)


def test_slices_never_cut_through_text_rows():
    rows = [(y, y + 30) for y in range(20, 2900, 80)]          # 30px 글자 줄, 50px 간격
    pieces = slice_image(text_lines(860, 3000, rows), max_width=1000, target_height=1000)
    assert len(pieces) >= 3
    assert all(p.height <= 1000 and boundary_rows_are_blank(p) for p in pieces)


def test_gray_side_borders_do_not_hide_gaps():
    """실제 공고: 회색 배경 위 흰 카드. 행 표준편차로는 여백을 못 찾던 회귀 케이스."""
    rows = [(y, y + 30) for y in range(20, 2900, 80)]
    img = text_lines(860, 3000, rows, background=(200, 200, 200), card=(40, 820))
    pieces = slice_image(img, max_width=1000, target_height=1000)
    assert all(boundary_rows_are_blank(p) for p in pieces)


def test_wide_image_is_scaled_and_blank_slices_are_dropped():
    img = text_lines(2000, 5000, [(y, y + 60) for y in range(40, 1600, 160)])  # 위쪽에만 글자
    pieces = slice_image(img, max_width=1000, target_height=1000)
    assert all(p.width == 1000 for p in pieces)
    assert len(pieces) == 1                                     # 아래쪽 빈 조각은 버림
