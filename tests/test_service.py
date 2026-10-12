"""사람인 대역(MockTransport)으로 수집 서비스 전체를 오프라인 검증한다."""
from io import BytesIO

import httpx
import pytest
from PIL import Image

from crawler.service import crawl
from crawler.snapshot import load_snapshot, snapshot_dir
from settings import Settings

VIEW = "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=123"


def png(w, h):
    buf = BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, "PNG")
    return buf.getvalue()


POSTER, TINY = png(860, 2000), png(40, 40)
DEFAULT_IMAGES = {"/upload/p1.png": POSTER, "/upload/tiny.png": TINY, "/upload/p2.png": POSTER}


class FakeSaramin:
    """경로별 응답을 바꿔 끼울 수 있는 사람인 대역. 없는 이미지 경로는 500."""

    def __init__(self, detail_html=None, images=None):
        self.detail_html = detail_html or (
            '<div class="user_content"><img src="/upload/p1.png">'
            '<img src="/upload/tiny.png"><img src="/upload/p2.png"></div>'
        )
        self.images = DEFAULT_IMAGES if images is None else images
        self.requests = []

    def handler(self, request):
        path = request.url.path
        self.requests.append((path, request.headers.get("referer")))
        if path.endswith("/relay/view"):
            return httpx.Response(200, text='<head><meta property="og:title" content="[OO산업] 회계팀 채용"></head>')
        if path.endswith("/view-detail"):
            return httpx.Response(200, text=self.detail_html)
        body = self.images.get(path)
        return httpx.Response(200, content=body) if body is not None else httpx.Response(500)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def settings(tmp_path):
    return Settings(data_dir=tmp_path, request_interval=0)


def test_crawl_saves_origin_snapshot(tmp_path):
    site = FakeSaramin()
    snap = crawl(VIEW, settings(tmp_path), client=site.client())
    d = snapshot_dir(tmp_path, "saramin", "123")

    assert [p for p, _ in site.requests] == [
        "/zf_user/jobs/relay/view", "/zf_user/jobs/relay/view-detail",
        "/upload/p1.png", "/upload/tiny.png", "/upload/p2.png",
    ]
    assert all(referer == VIEW for _, referer in site.requests[1:])
    assert (snap.source.site, snap.source.posting_id, snap.source.method) == ("saramin", "123", "crawl")
    assert snap.title == "[OO산업] 회계팀 채용"
    assert [(i.index, i.path, i.format, i.width, i.height) for i in snap.images] == [
        (0, "images/00.png", "PNG", 860, 2000),
        (1, "images/01.png", "PNG", 860, 2000),
    ]
    assert (d / "images" / "01.png").read_bytes() == POSTER          # 원본 바이트 그대로
    assert snap.skipped_images == ["https://www.saramin.co.kr/upload/tiny.png"]
    assert snap.is_image_posting
    assert (d / "detail.html").exists() and (d / "view.html").exists()
    assert load_snapshot(d) == snap


def test_second_crawl_reuses_snapshot_without_network(tmp_path):
    site = FakeSaramin()
    first = crawl("123", settings(tmp_path), client=site.client())
    count = len(site.requests)
    assert crawl("123", settings(tmp_path), client=site.client()) == first
    assert len(site.requests) == count


def test_refresh_recrawls_and_removes_stale_images(tmp_path):
    site = FakeSaramin()
    crawl("123", settings(tmp_path), client=site.client())
    site.detail_html = '<div class="user_content"><img src="/upload/p1.png"></div>'
    snap = crawl("123", settings(tmp_path), client=site.client(), refresh=True)
    assert [i.path for i in snap.images] == ["images/00.png"]
    images_dir = snapshot_dir(tmp_path, "saramin", "123") / "images"
    assert sorted(p.name for p in images_dir.iterdir()) == ["00.png"]


def test_text_posting_is_flagged_but_saved(tmp_path):
    site = FakeSaramin(detail_html='<div class="user_content"><p>' + "담당업무 " * 100 + "</p></div>")
    snap = crawl("123", settings(tmp_path), client=site.client())
    assert snap.images == [] and not snap.is_image_posting
    assert load_snapshot(snapshot_dir(tmp_path, "saramin", "123")) is not None


def test_failed_image_download_leaves_no_manifest(tmp_path):
    site = FakeSaramin(images={"/upload/p1.png": POSTER})  # tiny, p2 → 500
    with pytest.raises(httpx.HTTPStatusError):
        crawl("123", settings(tmp_path), client=site.client())
    assert load_snapshot(snapshot_dir(tmp_path, "saramin", "123")) is None
