"""사람인 HTML 규칙 (비공식 수집, 공식 Open API 미사용).

네트워크 없이 문자열만 다루는 순수 함수만 둔다.
사이트 구조에 대한 가정은 이 파일의 상수에만 둔다 — Task 9에서 실제 페이지로 검증 (ADR-0004).
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

BASE = "https://www.saramin.co.kr"
VIEW_URL = BASE + "/zf_user/jobs/relay/view?rec_idx={rec_idx}"                    # 공고 페이지
DETAIL_URL = BASE + "/zf_user/jobs/relay/view-detail?rec_idx={rec_idx}&rec_seq=0"  # 상세 본문 iframe (H1)
CONTENT_SELECTORS = [".user_content"]                                              # 본문 영역 (H2)
IGNORED_SRC = re.compile(r"(logo|icon|blank|spacer|\.svg$)", re.I)
# 화면에 보이지 않게 숨긴 요소 (사람인은 본문에 font-size:0 직무 카테고리 키워드 블록을 넣는다)
HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|rem|%)?\s*(?:;|!|$)", re.I
)


def parse_rec_idx(ref: str) -> str:
    """공고 URL 또는 숫자 문자열에서 rec_idx를 꺼낸다."""
    ref = ref.strip()
    if ref.isdigit():
        return ref
    values = parse_qs(urlparse(ref).query).get("rec_idx", [])
    if values and values[0].isdigit():
        return values[0]
    raise ValueError(f"rec_idx를 찾을 수 없습니다: {ref!r}")


def _content_root(soup: BeautifulSoup):
    """본문 영역. 가정한 셀렉터가 없으면 문서 전체로 대체한다."""
    for selector in CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node is not None:
            return node
    return soup


def extract_image_urls(html: str, base_url: str = BASE) -> list[str]:
    """상세 본문의 이미지 URL을 문서 순서대로. 로고·아이콘·data URI·중복 제외."""
    root = _content_root(BeautifulSoup(html, "html.parser"))
    urls: list[str] = []
    for img in root.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:") or IGNORED_SRC.search(src):
            continue
        absolute = urljoin(base_url, src)
        if absolute not in urls:
            urls.append(absolute)
    return urls


def body_text_length(html: str) -> int:
    """본문 영역에서 화면에 보이는 텍스트 길이(공백 제외). 이미지형 공고 판별 근거."""
    root = _content_root(BeautifulSoup(html, "html.parser"))
    for tag in root(["script", "style"]):
        tag.decompose()
    for tag in root.find_all(style=HIDDEN_STYLE):
        tag.decompose()
    return len(re.sub(r"\s+", "", root.get_text()))


def extract_title(view_html: str) -> Optional[str]:
    """공고 식별용 제목 (og:title → <title>). 매칭 조건으로는 쓰지 않는다."""
    soup = BeautifulSoup(view_html, "html.parser")
    og = soup.find("meta", attrs={"property": "og:title"})
    if og is not None and og.get("content", "").strip():
        return og["content"].strip()
    if soup.title is not None and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    return None
