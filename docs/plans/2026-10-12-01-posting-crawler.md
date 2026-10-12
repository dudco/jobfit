# 01. 공고 이미지 수집 (crawler) 구현 계획

> **에이전트 작업자용:** 필수 하위 스킬 — `superpowers:executing-plans`(또는 `superpowers:subagent-driven-development`)로 태스크 단위로 실행한다. 단계는 체크박스(`- [ ]`)로 추적한다.

> **레이아웃 변경 (Task 8 이후, [ADR-0006](../adr/0006-flat-src-layout.md)):** Task 1–8은 `src/jobfit/` 패키지 구조로 작성·구현되었고, 이후 소스를 `src/` 바로 아래로 옮겼다. Task 1–8 본문은 실행 당시 기록으로 남겨 둔다. 현재 경로로 읽을 때: `src/jobfit/X` → `src/X`, `from jobfit.X import …` → `from X import …`, `from jobfit import cli` → `import cli`.

**스펙:** [2026-10-12-01-posting-crawler-design.md](../specs/2026-10-12-01-posting-crawler-design.md)

**목표:** `jobfit crawl <사람인 URL>`로 이미지형 공고의 원본(HTML·본문 이미지)을 `data/postings/saramin/{rec_idx}/`에 스냅샷으로 저장하고, 실제 공고 2건으로 사이트 가정(H1–H4)을 검증한다.

**아키텍처:** 사이트 규칙(`crawler/saramin.py`, 순수 함수) / 이미지 검사(`crawler/images.py`) / 저장 형식(`crawler/snapshot.py`) / 오케스트레이션(`crawler/service.py`) / 어댑터(`cli.py`). 네트워크는 `httpx.Client`를 주입받아 테스트에서 `MockTransport`로 바꾼다.

**기술 스택:** Python 3.10+, uv, pydantic v2, httpx, BeautifulSoup, Pillow, Typer, rich, pytest ([ADR-0003](../adr/0003-python-stack.md))

**선행 조건:** 빈 레포 (문서만 있음)

| # | 태스크 | 종류 |
|---|---|---|
| 1 | 프로젝트 셋업 + 설정 | TDD |
| 2 | rec_idx 파싱 | TDD |
| 3 | 본문 이미지 URL 추출 | TDD |
| 4 | 본문 텍스트 길이, 공고 제목 | TDD |
| 5 | 이미지 검사 | TDD |
| 6 | 스냅샷 모델·저장 | TDD |
| 7 | 수집 서비스 | TDD (MockTransport) |
| 8 | CLI | TDD (CliRunner) |
| 9 | 실제 사람인 구조 검증 (H1–H4) | 수동 + 회귀 테스트 |
| 10 | 공고 2건 수집과 관찰 기록 | 수동 |

---

### Task 1: 프로젝트 셋업 + 설정

**Files:**
- Create: `pyproject.toml`, `.env.example`, `src/jobfit/__init__.py`, `src/jobfit/settings.py`, `tests/__init__.py`
- Test: `tests/test_settings.py`

- [x] **Step 1: 프로젝트 파일 작성**

`pyproject.toml`:

```toml
[project]
name = "jobfit"
version = "0.1.0"
description = "이미지 채용공고를 수집·구조화해 지원자와 매칭·랭킹하는 엔진"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
  "pydantic>=2.6",
  "httpx>=0.27",
  "beautifulsoup4>=4.12",
  "pillow>=10.0",
  "typer>=0.12",
  "rich>=13.0",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
jobfit = "jobfit.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/jobfit"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

`.env.example`:

```
# JOBFIT_DATA_DIR=data
# JOBFIT_REQUEST_INTERVAL=1.5
```

`src/jobfit/__init__.py`:

```python
"""jobfit — 이미지 채용공고 수집·구조화·매칭."""

__version__ = "0.1.0"
```

`tests/__init__.py`: 빈 파일

- [x] **Step 2: 실패하는 테스트 작성**

`tests/test_settings.py`:

```python
from jobfit.settings import load_settings

KEYS = ("JOBFIT_DATA_DIR", "JOBFIT_REQUEST_INTERVAL")


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBFIT_REQUEST_INTERVAL", "0")
    s = load_settings()
    assert s.data_dir == tmp_path
    assert s.request_interval == 0.0


def test_defaults(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert s.data_dir.name == "data"
    assert s.request_interval == 1.5
    assert "Mozilla" in s.user_agent
```

- [x] **Step 3: 설치 후 실패 확인**

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest tests/test_settings.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'jobfit.settings'`

- [x] **Step 4: 구현**

`src/jobfit/settings.py`:

```python
"""실행 설정 (환경변수 / .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    user_agent: str = DEFAULT_UA
    request_interval: float = 1.5  # 초. 요청마다 이만큼 쉰다


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    return Settings(
        data_dir=Path(os.environ.get("JOBFIT_DATA_DIR", ROOT / "data")),
        request_interval=float(os.environ.get("JOBFIT_REQUEST_INTERVAL", "1.5")),
    )
```

- [x] **Step 5: 통과 확인**

Run: `pytest tests/test_settings.py -v`
Expected: 2 passed

- [x] **Step 6: 커밋**

```bash
git add pyproject.toml .env.example src tests
git commit -m "chore: 프로젝트 셋업과 환경변수 기반 설정"
```

---

### Task 2: rec_idx 파싱

**Files:**
- Create: `src/jobfit/crawler/__init__.py` (빈 파일), `src/jobfit/crawler/saramin.py`
- Test: `tests/test_saramin.py`

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_saramin.py`:

```python
import pytest

from jobfit.crawler.saramin import parse_rec_idx


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
```

- [x] **Step 2: 실패 확인**

Run: `pytest tests/test_saramin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobfit.crawler'`

- [x] **Step 3: 구현**

`src/jobfit/crawler/saramin.py`:

```python
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
```

- [x] **Step 4: 통과 확인**

Run: `pytest tests/test_saramin.py -v`
Expected: 7 passed

- [x] **Step 5: 커밋**

```bash
git add src/jobfit/crawler tests/test_saramin.py
git commit -m "feat(crawler): 사람인 URL에서 rec_idx 파싱"
```

---

### Task 3: 본문 이미지 URL 추출

**Files:**
- Modify: `src/jobfit/crawler/saramin.py`
- Test: `tests/test_saramin.py`

- [x] **Step 1: 실패하는 테스트 추가**

```python
from jobfit.crawler.saramin import extract_image_urls

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
```

- [x] **Step 2: 실패 확인**

Run: `pytest tests/test_saramin.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_image_urls'`

- [x] **Step 3: 구현**

`src/jobfit/crawler/saramin.py`에 추가:

```python
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
```

- [x] **Step 4: 통과 확인**

Run: `pytest tests/test_saramin.py -v`
Expected: 9 passed

- [x] **Step 5: 커밋**

```bash
git add src/jobfit/crawler/saramin.py tests/test_saramin.py
git commit -m "feat(crawler): 상세 본문 이미지 URL 추출"
```

---

### Task 4: 본문 텍스트 길이, 공고 제목

**Files:**
- Modify: `src/jobfit/crawler/saramin.py`
- Test: `tests/test_saramin.py`

- [x] **Step 1: 실패하는 테스트 추가**

```python
from jobfit.crawler.saramin import body_text_length, extract_title


def test_body_text_length_ignores_whitespace_scripts_and_outside_text():
    html = ('<div class="user_content"><p>자격 요건</p><script>var x = 1;</script>'
            '<style>p {}</style></div><div>본문 밖</div>')
    assert body_text_length(html) == 4  # "자격요건"


def test_extract_title_prefers_og_title_then_title_tag():
    assert extract_title('<head><meta property="og:title" content=" [OO] 회계 채용 ">'
                         '<title>사람인</title></head>') == "[OO] 회계 채용"
    assert extract_title("<head><title> 회계 채용 | 사람인 </title></head>") == "회계 채용 | 사람인"
    assert extract_title("<html></html>") is None
```

- [x] **Step 2: 실패 확인**

Run: `pytest tests/test_saramin.py -v`
Expected: FAIL — `ImportError: cannot import name 'body_text_length'`

- [x] **Step 3: 구현**

`src/jobfit/crawler/saramin.py`에 추가:

```python
def body_text_length(html: str) -> int:
    """본문 영역의 텍스트 길이(공백 제외). 이미지형 공고 판별 근거."""
    root = _content_root(BeautifulSoup(html, "html.parser"))
    for tag in root(["script", "style"]):
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
```

- [x] **Step 4: 통과 확인**

Run: `pytest tests/test_saramin.py -v`
Expected: 11 passed

- [x] **Step 5: 커밋**

```bash
git add src/jobfit/crawler/saramin.py tests/test_saramin.py
git commit -m "feat(crawler): 본문 텍스트 길이와 공고 제목 추출"
```

---

### Task 5: 이미지 검사

**Files:**
- Create: `src/jobfit/crawler/images.py`
- Test: `tests/test_images.py`

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_images.py`:

```python
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
```

- [x] **Step 2: 실패 확인**

Run: `pytest tests/test_images.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobfit.crawler.images'`

- [x] **Step 3: 구현**

`src/jobfit/crawler/images.py`:

```python
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
```

- [x] **Step 4: 통과 확인**

Run: `pytest tests/test_images.py -v`
Expected: 3 passed

- [x] **Step 5: 커밋**

```bash
git add src/jobfit/crawler/images.py tests/test_images.py
git commit -m "feat(crawler): 내려받은 이미지 검사와 메타데이터"
```

---

### Task 6: 스냅샷 모델·저장

**Files:**
- Create: `src/jobfit/crawler/snapshot.py`
- Test: `tests/test_snapshot.py`

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_snapshot.py`:

```python
import json

from jobfit.crawler.snapshot import (
    PostingSnapshot, SourceRef, StoredFile, list_snapshots, load_snapshot, save_file, save_snapshot, snapshot_dir,
)


def make(posting_id="1"):
    return PostingSnapshot(
        source=SourceRef(site="saramin", posting_id=posting_id, url="u"),
        fetched_at="2026-10-12T00:00:00+00:00",
        detail_html=StoredFile(path="detail.html", sha256="x", bytes=1),
        body_text_length=0,
        is_image_posting=False,
    )


def test_save_file_writes_bytes_and_records_hash(tmp_path):
    f = save_file(tmp_path, "images/00.png", b"abc")
    assert (tmp_path / "images" / "00.png").read_bytes() == b"abc"
    assert (f.path, f.bytes) == ("images/00.png", 3)
    assert f.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_snapshot_roundtrip_with_atomic_write(tmp_path):
    d = snapshot_dir(tmp_path, "saramin", "1")
    assert load_snapshot(d) is None
    path = save_snapshot(d, make())
    assert path == tmp_path / "postings" / "saramin" / "1" / "snapshot.json"
    assert load_snapshot(d) == make()
    assert not list(d.glob("*.tmp"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1 and raw["source"]["method"] == "crawl"


def test_list_snapshots_is_sorted_and_tolerates_missing_dir(tmp_path):
    for pid in ("2", "1"):
        save_snapshot(snapshot_dir(tmp_path, "saramin", pid), make(pid))
    assert [s.source.posting_id for s in list_snapshots(tmp_path)] == ["1", "2"]
    assert list_snapshots(tmp_path / "empty") == []
```

- [x] **Step 2: 실패 확인**

Run: `pytest tests/test_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobfit.crawler.snapshot'`

- [x] **Step 3: 구현**

`src/jobfit/crawler/snapshot.py`:

```python
"""수집 단계 산출물: 공고 원본 스냅샷과 매니페스트 (ADR-0005).

다음 단계(전처리)는 사람인이 아니라 이 매니페스트만 입력으로 받는다.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

SNAPSHOT_FILE = "snapshot.json"


class SourceRef(BaseModel):
    site: str                                   # "saramin"
    method: Literal["crawl", "upload"] = "crawl"  # upload: 운영 시 고객사 경유 유입 (자리만)
    posting_id: str                             # 사람인 rec_idx
    url: str                                    # 사람이 보는 공고 페이지


class StoredFile(BaseModel):
    path: str      # 스냅샷 디렉터리 기준 상대경로
    sha256: str
    bytes: int


class StoredImage(StoredFile):
    index: int     # 본문 내 순서 (저장된 이미지 기준 0부터)
    source_url: str
    format: str
    width: int
    height: int


class PostingSnapshot(BaseModel):
    schema_version: int = 1
    source: SourceRef
    fetched_at: str
    title: Optional[str] = None                 # 식별용 메타데이터 — 매칭 조건으로 쓰지 않음
    view_html: Optional[StoredFile] = None
    detail_html: StoredFile
    images: list[StoredImage] = Field(default_factory=list)
    skipped_images: list[str] = Field(default_factory=list)
    body_text_length: int
    is_image_posting: bool


def snapshot_dir(data_dir: Path, site: str, posting_id: str) -> Path:
    return data_dir / "postings" / site / posting_id


def save_file(directory: Path, rel_path: str, data: bytes) -> StoredFile:
    """원본 바이트를 그대로 저장하고 해시·크기를 돌려준다."""
    path = directory / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return StoredFile(path=rel_path, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


def save_snapshot(directory: Path, snapshot: PostingSnapshot) -> Path:
    """매니페스트는 마지막에, 원자적으로 쓴다 — 매니페스트가 있으면 완전한 스냅샷이다."""
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / SNAPSHOT_FILE
    tmp = final.with_suffix(".json.tmp")
    tmp.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, final)
    return final


def load_snapshot(directory: Path) -> Optional[PostingSnapshot]:
    path = directory / SNAPSHOT_FILE
    if not path.exists():
        return None
    return PostingSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def list_snapshots(data_dir: Path) -> list[PostingSnapshot]:
    paths = sorted((data_dir / "postings").glob(f"*/*/{SNAPSHOT_FILE}"))
    return [PostingSnapshot.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]
```

- [x] **Step 4: 통과 확인**

Run: `pytest tests/test_snapshot.py -v`
Expected: 3 passed

- [x] **Step 5: 커밋**

```bash
git add src/jobfit/crawler/snapshot.py tests/test_snapshot.py
git commit -m "feat(crawler): 공고 원본 스냅샷 매니페스트와 원자적 저장"
```

---

### Task 7: 수집 서비스

**Files:**
- Create: `src/jobfit/crawler/service.py`
- Test: `tests/test_service.py`

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_service.py`:

```python
"""사람인 대역(MockTransport)으로 수집 서비스 전체를 오프라인 검증한다."""
from io import BytesIO

import httpx
import pytest
from PIL import Image

from jobfit.crawler.service import crawl
from jobfit.crawler.snapshot import load_snapshot, snapshot_dir
from jobfit.settings import Settings

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
```

- [x] **Step 2: 실패 확인**

Run: `pytest tests/test_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobfit.crawler.service'`

- [x] **Step 3: 구현**

`src/jobfit/crawler/service.py`:

```python
"""수집 서비스. CLI·API·UI가 공통으로 호출한다 (ADR-0002)."""
from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import httpx

from ..settings import Settings
from . import saramin
from .images import extension, inspect_image
from .snapshot import (
    SNAPSHOT_FILE, PostingSnapshot, SourceRef, StoredImage, load_snapshot, save_file, save_snapshot, snapshot_dir,
)

SITE = "saramin"
IMAGE_POSTING_MAX_TEXT = 300  # 본문 텍스트(공백 제외)가 이보다 길면 이미지형 공고로 보지 않는다

Log = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def make_client(settings: Settings) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": settings.user_agent}, follow_redirects=True, timeout=20)


def crawl(ref: str, settings: Settings, *, client: httpx.Client,
          refresh: bool = False, log: Log = _noop) -> PostingSnapshot:
    """공고 1건을 스냅샷으로 저장한다. 완전한 스냅샷이 있으면 네트워크 없이 재사용한다."""
    rec_idx = saramin.parse_rec_idx(ref)
    target = snapshot_dir(settings.data_dir, SITE, rec_idx)
    existing = load_snapshot(target)
    if existing is not None and not refresh:
        log(f"[crawl] 스냅샷 재사용: {target}")
        return existing

    view_url = saramin.VIEW_URL.format(rec_idx=rec_idx)
    referer = {"Referer": view_url}
    log(f"[crawl] 사람인 공고 {rec_idx} 수집")
    view = _get(client, settings, view_url)
    detail = _get(client, settings, saramin.DETAIL_URL.format(rec_idx=rec_idx), referer)

    # 이전 스냅샷 무효화: 매니페스트를 먼저 지워, 이후 실패해도 불완전한 스냅샷이 남지 않게
    (target / SNAPSHOT_FILE).unlink(missing_ok=True)
    shutil.rmtree(target / "images", ignore_errors=True)

    images: list[StoredImage] = []
    skipped: list[str] = []
    for url in saramin.extract_image_urls(detail.text):
        resp = _get(client, settings, url, referer)
        info = inspect_image(resp.content)
        if info is None:
            skipped.append(url)
            continue
        stored = save_file(target, f"images/{len(images):02d}{extension(info)}", resp.content)
        images.append(StoredImage(**stored.model_dump(), index=len(images), source_url=url,
                                  format=info.format, width=info.width, height=info.height))

    text_length = saramin.body_text_length(detail.text)
    snapshot = PostingSnapshot(
        source=SourceRef(site=SITE, posting_id=rec_idx, url=view_url),
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        title=saramin.extract_title(view.text),
        view_html=save_file(target, "view.html", view.content),
        detail_html=save_file(target, "detail.html", detail.content),
        images=images,
        skipped_images=skipped,
        body_text_length=text_length,
        is_image_posting=bool(images) and text_length <= IMAGE_POSTING_MAX_TEXT,
    )
    save_snapshot(target, snapshot)
    log(f"[crawl] 이미지 {len(images)}장 저장, 제외 {len(skipped)}건 → {target}")
    return snapshot


def _get(client: httpx.Client, settings: Settings, url: str,
         headers: Optional[dict] = None) -> httpx.Response:
    time.sleep(settings.request_interval)
    resp = client.get(url, headers=headers)
    resp.raise_for_status()
    return resp
```

- [x] **Step 4: 통과 확인**

Run: `pytest -q`
Expected: 전부 PASS

- [x] **Step 5: 커밋**

```bash
git add src/jobfit/crawler/service.py tests/test_service.py
git commit -m "feat(crawler): 공고 수집 서비스 (스냅샷 재사용, 실패 시 매니페스트 없음)"
```

---

### Task 8: CLI

**Files:**
- Create: `src/jobfit/cli.py`
- Test: `tests/test_cli.py`

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_cli.py`:

```python
from typer.testing import CliRunner

from jobfit import cli
from jobfit.crawler import service
from jobfit.crawler.snapshot import (
    PostingSnapshot, SourceRef, StoredFile, StoredImage, save_snapshot, snapshot_dir,
)


def snap(posting_id, title):
    return PostingSnapshot(
        source=SourceRef(site="saramin", posting_id=posting_id, url="u"),
        fetched_at="2026-10-12T00:00:00+00:00",
        title=title,
        detail_html=StoredFile(path="detail.html", sha256="x", bytes=1),
        images=[StoredImage(path="images/00.jpg", sha256="y", bytes=1, index=0, source_url="s",
                            format="JPEG", width=860, height=4000)],
        body_text_length=0,
        is_image_posting=True,
    )


def test_crawl_command_crawls_each_ref(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    seen = []

    def fake_crawl(ref, settings, *, client, refresh, log):
        seen.append((ref, refresh, settings.data_dir))
        return snap(ref, f"공고 {ref}")

    monkeypatch.setattr(service, "crawl", fake_crawl)
    result = CliRunner().invoke(cli.app, ["crawl", "111", "222", "--refresh"])
    assert result.exit_code == 0, result.output
    assert seen == [("111", True, tmp_path), ("222", True, tmp_path)]
    assert "111  이미지 1장  이미지 공고  공고 111" in result.output


def test_postings_lists_saved_snapshots(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    save_snapshot(snapshot_dir(tmp_path, "saramin", "111"), snap("111", "회계팀"))
    result = CliRunner().invoke(cli.app, ["postings"])
    assert result.exit_code == 0, result.output
    assert "111" in result.output and "회계팀" in result.output
```

- [x] **Step 2: 실패 확인**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'cli' from 'jobfit'`

- [x] **Step 3: 구현**

`src/jobfit/cli.py`:

```python
"""CLI 어댑터. 서비스 함수를 호출하고 결과를 출력만 한다 (ADR-0002)."""
from __future__ import annotations

from typing import List

import typer
from rich.console import Console
from rich.table import Table

from .crawler import service
from .crawler.snapshot import list_snapshots
from .settings import load_settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="이미지 채용공고 수집·구조화·매칭")
console = Console()


def _log(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")


@app.command()
def crawl(
    refs: List[str] = typer.Argument(..., help="사람인 공고 URL 또는 rec_idx (여러 개 가능)"),
    refresh: bool = typer.Option(False, "--refresh", help="기존 스냅샷을 무시하고 다시 수집"),
):
    """공고 원본(HTML·본문 이미지)을 data/postings/에 스냅샷으로 저장."""
    settings = load_settings()
    with service.make_client(settings) as client:
        for ref in refs:
            snap = service.crawl(ref, settings, client=client, refresh=refresh, log=_log)
            kind = "이미지 공고" if snap.is_image_posting else "[yellow]이미지 공고 아님?[/yellow]"
            console.print(f"{snap.source.posting_id}  이미지 {len(snap.images)}장  {kind}  {snap.title or ''}")


@app.command()
def postings():
    """저장된 공고 스냅샷 목록."""
    settings = load_settings()
    table = Table("사이트", "ID", "이미지", "이미지 공고", "수집 시각", "제목")
    for s in list_snapshots(settings.data_dir):
        table.add_row(s.source.site, s.source.posting_id, str(len(s.images)),
                      "예" if s.is_image_posting else "아니오", s.fetched_at, s.title or "")
    console.print(table)
```

- [x] **Step 4: 통과 확인**

```bash
pytest -q
jobfit --help
```
Expected: 전부 PASS, 도움말에 `crawl`, `postings`

- [x] **Step 5: 커밋**

```bash
git add src/jobfit/cli.py tests/test_cli.py
git commit -m "feat(cli): jobfit crawl / jobfit postings"
```

---

### Task 9: 실제 사람인 구조 검증 [수동] — H1–H4

**Files:**
- Create: `tests/fixtures/saramin_detail_real.html`
- Modify: `tests/test_saramin.py`, (필요 시) `src/crawler/saramin.py`, `docs/adr/0004-crawl-detail-iframe-over-http.md`, 스펙 9장

- [ ] **Step 1: 공고 A 고르기**

사람인에서 **본문이 거의 이미지인** 공고를 고른다. 자격요건·우대사항이 이미지 안에 있고, 회사 고유 용어가 적은 범용 직무(권장: 사무직).

- [ ] **Step 2: 수집 시도**

```bash
jobfit crawl "<공고 A URL>"
```
기대 결과: `<rec_idx>  이미지 N장  이미지 공고  <제목>` (N ≥ 1)

- [ ] **Step 3: 결과별 대응**

| 결과 | 의미 | 조치 |
|---|---|---|
| 이미지 N장, 이미지 공고 | H1·H2·H3 성립 | Step 4로 |
| HTTP 4xx/5xx | H1(경로) 또는 H3(헤더) 틀림 | 브라우저 개발자도구 Network에서 `view-detail` 요청의 실제 URL·헤더 확인 → `DETAIL_URL` 또는 요청 헤더 수정 |
| 이미지 0장 | H2(셀렉터) 틀림 | `data/postings/saramin/<ID>/detail.html`에서 포스터 `<img>`를 감싼 요소 확인 → `CONTENT_SELECTORS` 수정 |
| 제외된 이미지에 포스터가 있음 | 이미지 수신 실패(차단 페이지) | `skipped_images` URL을 브라우저에서 열어 확인 → 헤더 보강 |

상수를 고칠 때는 TDD로: 먼저 Step 4의 실제 HTML 테스트를 추가해 실패를 확인한 뒤 고친다. 고친 뒤 `jobfit crawl "<URL>" --refresh`.

- [ ] **Step 4: 실제 HTML을 회귀 fixture로**

```bash
mkdir -p tests/fixtures
cp data/postings/saramin/<ID>/detail.html tests/fixtures/saramin_detail_real.html
```

`tests/test_saramin.py`에 추가:

```python
from pathlib import Path

REAL = Path(__file__).parent / "fixtures" / "saramin_detail_real.html"


@pytest.mark.skipif(not REAL.exists(), reason="실제 사람인 상세 HTML 없음")
def test_real_detail_html_is_image_posting():
    html = REAL.read_text(encoding="utf-8")
    urls = extract_image_urls(html)
    assert urls and all(u.startswith("http") for u in urls)
    assert body_text_length(html) <= 300
```

Run: `pytest tests/test_saramin.py -v`
Expected: 12 passed

- [ ] **Step 5: 기록**

- 스펙 9장 표의 H1–H4 행 (공고 A)
- 가정이 틀려 상수를 고쳤다면 ADR-0004의 "결정"과 상태 갱신

- [ ] **Step 6: 커밋**

```bash
git add tests src/crawler docs
git commit -m "test(crawler): 실제 사람인 상세 HTML로 사이트 가정(H1–H4) 검증"
```

---

### Task 10: 공고 2건 수집과 관찰 기록 [수동]

**Files:**
- Create: `data/postings/saramin/<A>/…`, `data/postings/saramin/<B>/…` (로컬 전용, [ADR-0007](../adr/0007-data-not-versioned.md))
- Modify: 스펙 9장, `docs/README.md`

- [ ] **Step 1: 공고 B 고르기**

A와 **다른 직군**의 이미지형 공고 (권장: 현장·기술직 — 생산, 품질, 물류 등).

- [ ] **Step 2: 수집과 재사용 확인**

```bash
jobfit crawl "<공고 B URL>"
jobfit crawl "<공고 A URL>" "<공고 B URL>"   # 두 번째: 스냅샷 재사용 로그, 네트워크 없음
jobfit postings
```
Expected: 두 공고 모두 `이미지 공고 = 예`

- [ ] **Step 3: 이미지 확인 [수동]**

`data/postings/saramin/<ID>/images/`를 열어:
- [ ] 공고 본문 포스터가 빠짐없이 순서대로 있다
- [ ] 로고·배너 같은 비본문 이미지가 섞이지 않았다
- [ ] `skipped_images`에 본문 포스터가 없다

- [ ] **Step 4: 관찰 기록**

매니페스트에서 수치를 뽑아 스펙 9장 표를 채운다:

```bash
python - <<'PY'
from crawler.snapshot import list_snapshots
from settings import load_settings

for s in list_snapshots(load_settings().data_dir):
    sizes = ", ".join(f"{i.width}x{i.height} {i.format}" for i in s.images)
    print(s.source.posting_id, s.title, f"text={s.body_text_length}", f"skipped={len(s.skipped_images)}", sizes, sep=" | ")
PY
```

"전처리 스펙에 넘길 사항"에 적을 것: 이미지 최대 세로 길이와 가로 대비 비율(슬라이싱 필요 여부), 공고당 이미지 장수, 형식(GIF·투명 PNG 여부).

- [ ] **Step 5: 상태 갱신과 커밋**

- 스펙 01 상태 → `완료`, 수용 기준 체크
- `docs/README.md` 진행 현황 01 → 완료

```bash
git add docs
git commit -m "docs: 공고 2건 수집 관찰 기록"   # data/는 커밋하지 않는다 (ADR-0007)
```
