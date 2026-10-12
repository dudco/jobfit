from io import BytesIO

from PIL import Image

from jobfit.crawler.images import ImageInfo, extension, inspect_image


def encode(fmt, w, h):
    buf = BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, fmt)
    return buf.getvalue()


def test_accepts_poster_and_reads_metadata():
    info = inspect_image(encode("JPEG", 860, 3000))
    assert (info.format, info.width, info.height) == ("JPEG", 860, 3000)
    assert extension(info) == ".jpg"


def test_rejects_icons_and_non_image_bytes():
    assert inspect_image(encode("PNG", 40, 40)) is None          # 아이콘 크기
    assert inspect_image(b"<html>403 Forbidden</html>") is None  # 차단 페이지
    assert inspect_image(b"") is None


def test_unknown_format_gets_generic_extension():
    assert extension(ImageInfo(format="TIFF", width=1, height=1)) == ".bin"
