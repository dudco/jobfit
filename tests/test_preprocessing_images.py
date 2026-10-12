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
