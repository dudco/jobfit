import pytest

from crawler.saramin import parse_rec_idx


@pytest.mark.parametrize("ref", [
    "51234567",
    " 51234567 ",
    "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=list&rec_idx=51234567",
    "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=51234567&location=ts",
])
def test_parse_rec_idx(ref):
    assert parse_rec_idx(ref) == "51234567"


@pytest.mark.parametrize("ref", ["", "abc", "https://www.saramin.co.kr/zf_user/search?searchword=회계"])
def test_parse_rec_idx_rejects_refs_without_id(ref):
    with pytest.raises(ValueError):
        parse_rec_idx(ref)


from crawler.saramin import extract_image_urls

DETAIL_HTML = """
<html><body>
<div class="header"><img src="/img/top_banner.png"></div>
<div class="user_content">
  <img src="//pds.saramin.co.kr/company/logo/logo_1.png">
  <p><img src="/upload/recruit/poster_1.jpg"></p>
  <p><img data-src="https://img.example.com/poster_2.png"></p>
  <img src="data:image/gif;base64,R0lGOD">
  <img src="/upload/recruit/poster_1.jpg">
</div>
</body></html>
"""


def test_extracts_body_images_in_document_order():
    assert extract_image_urls(DETAIL_HTML) == [
        "https://www.saramin.co.kr/upload/recruit/poster_1.jpg",  # 상대경로 보정, 중복 제거
        "https://img.example.com/poster_2.png",                    # data-src 지원
    ]  # 본문 밖 배너, 로고, data URI 제외


def test_falls_back_to_whole_document_without_content_container():
    assert extract_image_urls('<img src="/a/poster.jpg">') == ["https://www.saramin.co.kr/a/poster.jpg"]


from crawler.saramin import body_text_length, extract_title


def test_body_text_length_ignores_whitespace_scripts_and_outside_text():
    html = ('<div class="user_content"><p>자격 요건</p><script>var x = 1;</script>'
            '<style>p {}</style></div><div>본문 밖</div>')
    assert body_text_length(html) == 4  # "자격요건"


def test_extract_title_prefers_og_title_then_title_tag():
    assert extract_title('<head><meta property="og:title" content=" [OO] 회계 채용 ">'
                         '<title>사람인</title></head>') == "[OO] 회계 채용"
    assert extract_title("<head><title> 회계 채용 | 사람인 </title></head>") == "회계 채용 | 사람인"
    assert extract_title("<html></html>") is None
