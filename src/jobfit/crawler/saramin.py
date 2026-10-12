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
