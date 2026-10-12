# 02. 공고 이미지 전처리·구조화 (preprocessing) 구현 계획

> **에이전트 작업자용:** 필수 하위 스킬 — `superpowers:executing-plans`(또는 `superpowers:subagent-driven-development`)로 태스크 단위로 실행한다. 단계는 체크박스(`- [ ]`)로 추적한다.

**스펙:** [2026-10-12-02-posting-preprocessing-design.md](../specs/2026-10-12-02-posting-preprocessing-design.md)

**목표:** `jobfit extract <rec_idx>`가 공고 스냅샷의 이미지만으로 `data/criteria/saramin/{rec_idx}/criteria.json`(구조화된 공고 조건)을 만들고, `jobfit evaluate`로 정답 대비 품질을 잰다.

**아키텍처:** 이미지 처리(`preprocessing/images.py`, Pillow, 결정적) → 전사(`transcribe.py`, 비전 LLM) → 구조화(`structure.py`, 텍스트 LLM) → 검증(`verify.py`, 코드) → 저장(`criteria.py`). 오케스트레이션은 `preprocessing/service.py`, LLM 경계와 캐시는 `src/llm.py`. LLM은 프로토콜로 주입해 테스트에서 `FakeLLM`으로 바꾼다.

**기술 스택:** Pillow, openai(Structured Output), pydantic v2, PyYAML(정답 파일), Typer, pytest

**선행 조건:** 계획 01 완료 (공고 스냅샷 2건). 태스크 12(실제 실행)만 `OPENAI_API_KEY` 필요.

| # | 태스크 | 종류 | 의존 |
|---|---|---|---|
| 1 | 설정 확장 (모델·분할 파라미터, 의존성) | TDD | — |
| 2 | 이미지 정규화 | TDD | 1 |
| 3 | 여백 기반 분할 | TDD | 2 |
| 4 | LLM 프로토콜·OpenAI 구현·응답 캐시 | TDD | 1 |
| 5 | `PostingCriteria` 모델·저장 | TDD | 1 |
| 6 | 프롬프트·전사 | TDD | 4 |
| 7 | 구조화 (LLM 출력 스키마) | TDD | 4, 5, 6 |
| 8 | 검증·후처리 | TDD | 5, 6, 7 |
| 9 | 전처리 서비스 | TDD | 3, 8 |
| 10 | CLI: extract / criteria / models | TDD | 9 |
| 11 | 평가 도구와 정답 목록 | TDD | 5, 10 |
| 12 | 실제 공고로 실행·실험 X1–X4 | 수동 (API 키) | 11 |

병렬 가능: 1 이후 [2→3], [4], [5]를 동시에. 이후 [6→7→8], 그다음 [9→10→11].

---

### Task 1: 설정 확장

**Files:**
- Modify: `pyproject.toml` (의존성), `src/settings.py` (전체 교체), `.env.example`
- Test: `tests/test_settings.py`

- [ ] **Step 1: 의존성 추가**

`pyproject.toml`의 `dependencies`에 추가:

```toml
  "openai>=1.100",
  "pyyaml>=6.0",
```

```bash
uv pip install -e ".[dev]"
```

- [ ] **Step 2: 실패하는 테스트 추가**

`tests/test_settings.py`에 추가:

```python
PREP_KEYS = ("JOBFIT_VISION_MODEL", "JOBFIT_TEXT_MODEL", "JOBFIT_SLICE_HEIGHT", "JOBFIT_MAX_WIDTH")


def test_preprocessing_settings_from_env(monkeypatch):
    monkeypatch.setenv("JOBFIT_VISION_MODEL", "v-model")
    monkeypatch.setenv("JOBFIT_TEXT_MODEL", "t-model")
    monkeypatch.setenv("JOBFIT_SLICE_HEIGHT", "0")
    monkeypatch.setenv("JOBFIT_MAX_WIDTH", "900")
    s = load_settings(dotenv_path=None)
    assert (s.vision_model, s.text_model, s.slice_height, s.max_width) == ("v-model", "t-model", 0, 900)


def test_preprocessing_defaults(monkeypatch, tmp_path):
    for k in PREP_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    s = load_settings(dotenv_path=None)
    assert s.vision_model and s.text_model
    assert (s.slice_height, s.max_width) == (1200, 1000)
    assert s.llm_cache_dir == tmp_path / "cache" / "llm"
```

- [ ] **Step 3: 실패 확인**

Run: `pytest tests/test_settings.py -v`
Expected: FAIL — `TypeError: load_settings() got an unexpected keyword argument 'dotenv_path'`

- [ ] **Step 4: 구현**

`src/settings.py` 전체:

```python
"""실행 설정 (환경변수 / .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]  # 레포 루트 (src/의 부모)
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
DEFAULT_VISION_MODEL = "gpt-4.1"      # 스펙 02 실험 X2로 확정 (ADR-0010)
DEFAULT_TEXT_MODEL = "gpt-4.1-mini"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    user_agent: str = DEFAULT_UA
    request_interval: float = 1.5      # 초. 사람인 요청마다 이만큼 쉰다
    vision_model: str = DEFAULT_VISION_MODEL
    text_model: str = DEFAULT_TEXT_MODEL
    slice_height: int = 1200           # 분할 목표 높이. 0 = 분할하지 않음 (ADR-0012)
    max_width: int = 1000              # 이보다 넓은 이미지는 비율 유지 축소

    @property
    def llm_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "llm"


def load_settings(*, dotenv_path: Optional[Path] = ROOT / ".env") -> Settings:
    """환경변수에서 설정을 읽는다. dotenv_path=None이면 .env를 읽지 않는다 (테스트용)."""
    if dotenv_path is not None:
        load_dotenv(dotenv_path)
    env = os.environ.get
    return Settings(
        data_dir=Path(env("JOBFIT_DATA_DIR", str(ROOT / "data"))),
        request_interval=float(env("JOBFIT_REQUEST_INTERVAL", "1.5")),
        vision_model=env("JOBFIT_VISION_MODEL", DEFAULT_VISION_MODEL),
        text_model=env("JOBFIT_TEXT_MODEL", DEFAULT_TEXT_MODEL),
        slice_height=int(env("JOBFIT_SLICE_HEIGHT", "1200")),
        max_width=int(env("JOBFIT_MAX_WIDTH", "1000")),
    )
```

`.env.example`:

```
OPENAI_API_KEY=
# JOBFIT_DATA_DIR=data
# JOBFIT_REQUEST_INTERVAL=1.5
# JOBFIT_VISION_MODEL=gpt-4.1
# JOBFIT_TEXT_MODEL=gpt-4.1-mini
# JOBFIT_SLICE_HEIGHT=1200        # 0 = 분할하지 않음
# JOBFIT_MAX_WIDTH=1000
```

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/test_settings.py -v`
Expected: 4 passed

- [ ] **Step 6: 커밋**

```bash
git add pyproject.toml .env.example src/settings.py tests/test_settings.py
git commit -m "feat(settings): 전처리 설정(모델·분할 높이·폭)과 openai·pyyaml 의존성"
```

---

### Task 2: 이미지 정규화

**Files:**
- Create: `src/preprocessing/__init__.py` (빈 파일), `src/preprocessing/images.py`
- Test: `tests/test_preprocessing_images.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_preprocessing_images.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'preprocessing'`

- [ ] **Step 3: 구현**

`src/preprocessing/images.py`:

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_preprocessing_images.py -v`
Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add src/preprocessing tests/test_preprocessing_images.py
git commit -m "feat(preprocessing): 이미지 정규화 (투명 배경 흰색 합성, GIF 첫 프레임)"
```

---

### Task 3: 여백 기반 분할

계획 작성 중 실제 공고 이미지로 확인한 사실: 행 **표준편차**로 여백을 찾으면, 포스터 좌우의 회색 배경·테두리 때문에 글자 없는 행도 값이 커서 여백을 하나도 찾지 못하고 표 행을 가로질러 잘랐다. 그래서 행 안의 **가로 방향 밝기 변화량**("잉크량")을 지표로 쓰고, 여백이 없을 때는 잉크가 가장 적은 행에서 자른다 ([ADR-0012](../adr/0012-whitespace-aware-slicing.md)).

**Files:**
- Modify: `src/preprocessing/images.py`
- Test: `tests/test_preprocessing_images.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_preprocessing_images.py -v`
Expected: FAIL — `ImportError: cannot import name 'INK_THRESHOLD'`

- [ ] **Step 3: 구현**

`src/preprocessing/images.py`에 추가:

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_preprocessing_images.py -v`
Expected: 9 passed

- [ ] **Step 5: 실제 이미지로 확인 [수동]**

```bash
python - <<'PY'
import sys; sys.path.insert(0, "src")
from pathlib import Path
from PIL import Image
from preprocessing.images import fit_width, normalize, plan_slices, row_ink
for pid in ("55189170", "55162188"):
    img = fit_width(normalize(Image.open(Path("data/postings/saramin") / pid / "images/00.png")), 1000)
    print(pid, img.size, plan_slices(row_ink(img), target_height=1200))
PY
```
Expected (계획 작성 시 확인 값): `55189170 (860, 3170) [(0, 916), (916, 1955), (1955, 2983), (2983, 3170)]`, `55162188 (720, 1890) [(0, 950), (950, 1890)]` — 모두 글자 줄 사이

- [ ] **Step 6: 커밋**

```bash
git add src/preprocessing/images.py tests/test_preprocessing_images.py
git commit -m "feat(preprocessing): 잉크량 기반 여백 분할 (여백 없으면 최소 잉크 행 + 겹침)"
```

---

### Task 4: LLM 프로토콜·OpenAI 구현·응답 캐시

**Files:**
- Create: `src/llm.py`, `tests/fakes.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: 테스트 대역 작성**

`tests/fakes.py`:

```python
"""LLM 프로토콜 대역. 실제 API를 호출하지 않는다."""
from __future__ import annotations


class FakeLLM:
    """vision: 응답 문자열 목록(순서대로 소비)
    structured: 응답 목록 — pydantic 객체, 또는 user 프롬프트를 받아 객체를 돌려주는 함수
    calls: [(종류, 태그)] — 호출 기록
    """

    def __init__(self, vision=None, structured=None):
        self.vision = list(vision or [])
        self.structured_responses = list(structured or [])
        self.calls: list[tuple[str, str]] = []
        self.vision_inputs: list[dict] = []

    def vision_text(self, *, model, system, image, user_text=None, tag=""):
        self.calls.append(("vision", tag))
        self.vision_inputs.append({"image": image, "user_text": user_text})
        return self.vision.pop(0)

    def structured(self, *, model, system, user, schema, tag=""):
        self.calls.append(("structured", tag))
        resp = self.structured_responses.pop(0)
        return resp(user) if callable(resp) else resp
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_llm.py`:

```python
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from llm import CachedLLM, OpenAILLM, image_data_url

from .fakes import FakeLLM


class Completions:
    """openai client.chat.completions 대역."""

    def __init__(self, parsed=None):
        self.parsed = parsed
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="전사 결과"))])

    def parse(self, **kwargs):
        self.kwargs = kwargs
        msg = SimpleNamespace(parsed=self.parsed, refusal="정책상 거부")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def client(comp):
    return SimpleNamespace(chat=SimpleNamespace(completions=comp))


class Out(BaseModel):
    v: int


def png(tmp_path, name="a.png", data=b"img-bytes"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_image_data_url_uses_mime_by_extension(tmp_path):
    assert image_data_url(png(tmp_path, "a.png")).startswith("data:image/png;base64,")
    assert image_data_url(png(tmp_path, "b.jpg")).startswith("data:image/jpeg;base64,")


def test_vision_text_sends_context_then_high_detail_image(tmp_path):
    comp = Completions()
    out = OpenAILLM(client(comp)).vision_text(model="m", system="sys", image=png(tmp_path), user_text="직전 줄")
    assert out == "전사 결과"
    system, user = comp.kwargs["messages"]
    assert system == {"role": "system", "content": "sys"}
    assert user["content"][0] == {"type": "text", "text": "직전 줄"}
    assert user["content"][1]["type"] == "image_url"
    assert user["content"][1]["image_url"]["detail"] == "high"


def test_structured_returns_parsed_or_raises_with_refusal():
    assert OpenAILLM(client(Completions(parsed=Out(v=1)))).structured(
        model="m", system="s", user="u", schema=Out) == Out(v=1)
    with pytest.raises(RuntimeError, match="정책상 거부"):
        OpenAILLM(client(Completions(parsed=None))).structured(model="m", system="s", user="u", schema=Out)


def test_cache_hit_skips_inner_llm_and_needs_no_client(tmp_path):
    inner = FakeLLM(vision=["첫 응답"], structured=[Out(v=7)])
    cached = CachedLLM(lambda: inner, tmp_path / "cache")
    img = png(tmp_path)
    assert cached.vision_text(model="m", system="s", image=img, tag="transcribe-1-00") == "첫 응답"
    assert cached.structured(model="m", system="s", user="u", schema=Out, tag="structure-1") == Out(v=7)

    def no_client():
        raise AssertionError("캐시 적중이면 내부 LLM을 만들지 않아야 한다 (API 키 불필요)")

    again = CachedLLM(no_client, tmp_path / "cache")
    assert again.vision_text(model="m", system="s", image=img, tag="transcribe-1-00") == "첫 응답"
    result = again.structured(model="m", system="s", user="u", schema=Out, tag="structure-1")
    assert result == Out(v=7) and isinstance(result, Out)
    assert len(list((tmp_path / "cache").glob("transcribe-1-00-*.json"))) == 1


def test_cache_key_changes_with_image_bytes_and_model(tmp_path):
    inner = FakeLLM(vision=["a", "b", "c"])
    cached = CachedLLM(lambda: inner, tmp_path / "cache")
    cached.vision_text(model="m", system="s", image=png(tmp_path, "x.png", b"1"))
    cached.vision_text(model="m", system="s", image=png(tmp_path, "y.png", b"2"))  # 이미지 바이트가 다름
    cached.vision_text(model="m2", system="s", image=png(tmp_path, "x.png", b"1"))  # 모델이 다름
    assert [kind for kind, _ in inner.calls] == ["vision", "vision", "vision"]


def test_empty_string_response_is_cached(tmp_path):
    inner = FakeLLM(vision=[""])
    cached = CachedLLM(lambda: inner, tmp_path / "cache")
    img = png(tmp_path)
    assert cached.vision_text(model="m", system="s", image=img) == ""
    assert cached.vision_text(model="m", system="s", image=img) == ""
    assert len(inner.calls) == 1
```

- [ ] **Step 3: 실패 확인**

Run: `pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm'`

- [ ] **Step 4: 구현**

`src/llm.py`:

```python
"""LLM 경계. 전처리·스코어링은 LLM 프로토콜에만 의존한다.

- OpenAILLM: 실제 OpenAI 호출
- CachedLLM: 다른 LLM을 감싸 응답을 디스크에 캐시 (ADR-0014)
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

MIME = {".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}


class LLM(Protocol):
    def vision_text(self, *, model: str, system: str, image: Path,
                    user_text: Optional[str] = None, tag: str = "") -> str: ...

    def structured(self, *, model: str, system: str, user: str, schema: type[T], tag: str = "") -> T: ...


def image_data_url(path: Path) -> str:
    mime = MIME.get(path.suffix.lower(), "image/jpeg")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


class OpenAILLM:
    def __init__(self, client=None):
        if client is None:
            from openai import OpenAI

            client = OpenAI()  # OPENAI_API_KEY 환경변수 사용
        self.client = client

    def vision_text(self, *, model: str, system: str, image: Path,
                    user_text: Optional[str] = None, tag: str = "") -> str:
        content: list[dict] = []
        if user_text:
            content.append({"type": "text", "text": user_text})
        content.append({"type": "image_url", "image_url": {"url": image_data_url(image), "detail": "high"}})
        resp = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
        )
        return resp.choices[0].message.content or ""

    def structured(self, *, model: str, system: str, user: str, schema: type[T], tag: str = "") -> T:
        resp = self.client.chat.completions.parse(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=schema,
        )
        msg = resp.choices[0].message
        if msg.parsed is None:
            raise RuntimeError(f"구조화 응답 실패: {msg.refusal}")
        return msg.parsed

    def list_models(self) -> list[str]:
        return sorted(m.id for m in self.client.models.list())


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class CachedLLM:
    """응답을 `{cache_dir}/{tag}-{hash16}.json`에 저장한다. 같은 입력이면 내부 LLM을 만들지도 부르지도 않는다."""

    def __init__(self, inner_factory: Callable[[], LLM], cache_dir: Path):
        self._factory = inner_factory
        self._inner: Optional[LLM] = None
        self.cache_dir = cache_dir

    @property
    def inner(self) -> LLM:
        if self._inner is None:
            self._inner = self._factory()
        return self._inner

    def vision_text(self, *, model: str, system: str, image: Path,
                    user_text: Optional[str] = None, tag: str = "") -> str:
        key = _hash({"kind": "vision", "model": model, "system": system, "user_text": user_text,
                     "image": hashlib.sha256(image.read_bytes()).hexdigest()})
        found, value = self._load(tag, key)
        if found:
            return value
        out = self.inner.vision_text(model=model, system=system, image=image, user_text=user_text, tag=tag)
        self._save(tag, key, model, out)
        return out

    def structured(self, *, model: str, system: str, user: str, schema: type[T], tag: str = "") -> T:
        key = _hash({"kind": "structured", "model": model, "system": system, "user": user,
                     "schema": schema.model_json_schema()})
        found, value = self._load(tag, key)
        if found:
            return schema.model_validate(value)
        out = self.inner.structured(model=model, system=system, user=user, schema=schema, tag=tag)
        self._save(tag, key, model, out.model_dump(mode="json"))
        return out

    def _path(self, tag: str, key: str) -> Path:
        safe = re.sub(r"[^\w.-]", "_", tag) or "call"
        return self.cache_dir / f"{safe}-{key[:16]}.json"

    def _load(self, tag: str, key: str) -> tuple[bool, Any]:
        path = self._path(tag, key)
        if not path.exists():
            return False, None
        return True, json.loads(path.read_text(encoding="utf-8"))["response"]

    def _save(self, tag: str, key: str, model: str, response: Any) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._path(tag, key).write_text(
            json.dumps({"tag": tag, "model": model, "response": response}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
```

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/test_llm.py -v`
Expected: 6 passed

- [ ] **Step 6: 커밋**

```bash
git add src/llm.py tests/fakes.py tests/test_llm.py
git commit -m "feat(llm): LLM 프로토콜, OpenAI 구현, 입력 해시 응답 캐시 (ADR-0014)"
```

---

### Task 5: `PostingCriteria` 모델·저장

**Files:**
- Create: `src/preprocessing/criteria.py`
- Test: `tests/test_criteria.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import json

import pytest
from pydantic import ValidationError

from preprocessing.criteria import (
    CriteriaSource, EvidenceRef, PostingCriteria, Requirement, criteria_dir, list_criteria, load_criteria,
    save_criteria,
)


def make(posting_id="1", requirements=()):
    return PostingCriteria(
        source=CriteriaSource(site="saramin", posting_id=posting_id,
                              snapshot_fetched_at="2026-10-12T00:00:00+00:00", image_sha256=["abc"]),
        extracted_at="2026-10-12T01:00:00+00:00",
        models={"transcribe": "v", "structure": "t"},
        title="생산직 채용", job_family="식품 생산",
        requirements=list(requirements),
        suitable=bool(requirements),
    )


def req(**kw):
    base = dict(id="r1", text="고등학교 졸업 이상", normalized="고졸 이상", priority="must",
                category="education", evidence=EvidenceRef(quote="고등학교 졸업 이상"))
    return Requirement(**{**base, **kw})


def test_requirement_rejects_unknown_category_and_priority():
    with pytest.raises(ValidationError):
        req(category="java")            # 스킬 이름은 유형이 아니다 (ADR-0013)
    with pytest.raises(ValidationError):
        req(priority="nice-to-have")


def test_requirement_defaults():
    r = req()
    assert (r.positions, r.sensitive, r.flags, r.min_years) == ([], False, [], None)


def test_criteria_roundtrip_with_atomic_write(tmp_path):
    d = criteria_dir(tmp_path, "saramin", "1")
    assert load_criteria(d) is None
    path = save_criteria(d, make(requirements=[req()]))
    assert path == tmp_path / "criteria" / "saramin" / "1" / "criteria.json"
    assert load_criteria(d) == make(requirements=[req()])
    assert not list(d.glob("*.tmp"))
    assert json.loads(path.read_text(encoding="utf-8"))["requirements"][0]["evidence"]["quote"] == "고등학교 졸업 이상"


def test_list_criteria_sorted(tmp_path):
    for pid in ("2", "1"):
        save_criteria(criteria_dir(tmp_path, "saramin", pid), make(pid))
    assert [c.source.posting_id for c in list_criteria(tmp_path)] == ["1", "2"]
    assert list_criteria(tmp_path / "none") == []
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_criteria.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'preprocessing.criteria'`

- [ ] **Step 3: 구현**

`src/preprocessing/criteria.py`:

```python
"""전처리 단계 산출물: 구조화된 공고 조건 (스펙 02 6장, ADR-0013).

스코어링 단계는 이 모델만 입력으로 받는다.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

CRITERIA_FILE = "criteria.json"

Priority = Literal["must", "preferred"]
Category = Literal[
    "experience", "education", "certification", "language",
    "skill", "domain_knowledge", "soft_skill", "other",
]
EducationLevel = Literal["none", "high_school", "associate", "bachelor", "master", "phd"]


class EvidenceRef(BaseModel):
    quote: str                          # 전사 텍스트에서 그대로 인용
    image_index: Optional[int] = None   # 코드가 채운다
    slice_index: Optional[int] = None


class Requirement(BaseModel):
    id: str                             # "r1"… 코드가 부여
    text: str
    normalized: str
    priority: Priority
    category: Category                  # 고정된 유형 — 내용은 데이터 (ADR-0013)
    positions: list[str] = Field(default_factory=list)   # 비어 있으면 모든 모집분야
    min_years: Optional[float] = None
    min_education: Optional[EducationLevel] = None
    sensitive: bool = False             # 법정 우대 등 민감 속성
    evidence: EvidenceRef
    flags: list[str] = Field(default_factory=list)


class Position(BaseModel):
    name: str
    group: Optional[str] = None
    duties: Optional[str] = None
    location: Optional[str] = None


class Conditions(BaseModel):
    """점수에 쓰지 않는 참고 정보."""

    employment_type: Optional[str] = None
    locations: list[str] = Field(default_factory=list)
    schedule: Optional[str] = None
    others: list[str] = Field(default_factory=list)


class CriteriaSource(BaseModel):
    site: str
    posting_id: str
    snapshot_fetched_at: str            # 어느 스냅샷에서 만들었나
    image_sha256: list[str]


class PostingCriteria(BaseModel):
    schema_version: int = 1
    source: CriteriaSource
    extracted_at: str
    models: dict[str, str]
    title: str                          # 이미지에서 읽은 공고명
    company: Optional[str] = None
    job_family: str                     # 자유 텍스트
    positions: list[Position] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    conditions: Conditions = Field(default_factory=Conditions)
    suitable: bool                      # 요건이 1개 이상 있는가
    warnings: list[str] = Field(default_factory=list)


def criteria_dir(data_dir: Path, site: str, posting_id: str) -> Path:
    return data_dir / "criteria" / site / posting_id


def save_criteria(directory: Path, criteria: PostingCriteria) -> Path:
    """마지막에, 원자적으로 쓴다 — criteria.json이 있으면 완전한 결과다."""
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / CRITERIA_FILE
    tmp = final.with_suffix(".json.tmp")
    tmp.write_text(criteria.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, final)
    return final


def load_criteria(directory: Path) -> Optional[PostingCriteria]:
    path = directory / CRITERIA_FILE
    if not path.exists():
        return None
    return PostingCriteria.model_validate_json(path.read_text(encoding="utf-8"))


def list_criteria(data_dir: Path) -> list[PostingCriteria]:
    paths = sorted((data_dir / "criteria").glob(f"*/*/{CRITERIA_FILE}"))
    return [PostingCriteria.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_criteria.py -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/preprocessing/criteria.py tests/test_criteria.py
git commit -m "feat(preprocessing): PostingCriteria 모델과 원자적 저장 (ADR-0013)"
```

---

### Task 6: 프롬프트·전사

**Files:**
- Create: `src/preprocessing/prompts.py`, `src/preprocessing/transcribe.py`
- Test: `tests/test_transcribe.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from preprocessing.transcribe import SliceRef, slice_at, transcribe

from .fakes import FakeLLM


def refs(tmp_path, spec):
    out = []
    for i, (image_index, part) in enumerate(spec):
        p = tmp_path / f"{image_index:02d}_{part:02d}.png"
        p.write_bytes(b"x")
        out.append(SliceRef(path=p, image_index=image_index, part=part))
    return out


def test_transcribe_marks_slices_and_passes_previous_tail(tmp_path):
    llm = FakeLLM(vision=["  ## 지원자격\n- 대학 졸업\n- 영어성적\n- 병역필  ", "- 우대: 영어 회화"])
    out = transcribe(llm, refs(tmp_path, [(0, 0), (0, 1)]), model="v", posting_id="55")

    assert out == ("<!-- slice 00 image=0 part=0 -->\n## 지원자격\n- 대학 졸업\n- 영어성적\n- 병역필\n\n"
                   "<!-- slice 01 image=0 part=1 -->\n- 우대: 영어 회화")
    assert [tag for _, tag in llm.calls] == ["transcribe-55-00", "transcribe-55-01"]
    assert llm.vision_inputs[0]["user_text"] is None
    assert llm.vision_inputs[1]["user_text"].endswith("- 대학 졸업\n- 영어성적\n- 병역필")  # 마지막 3줄만
    assert "## 지원자격" not in llm.vision_inputs[1]["user_text"]


def test_slice_at_finds_the_slice_containing_an_offset(tmp_path):
    text = transcribe(FakeLLM(vision=["첫 조각", "둘째 조각"]), refs(tmp_path, [(0, 0), (1, 0)]),
                      model="v", posting_id="55")
    assert slice_at(text, text.index("첫 조각")) == (0, 0)
    assert slice_at(text, text.index("둘째 조각")) == (1, 1)
    assert slice_at("마커 없음", 0) == (None, None)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_transcribe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'preprocessing.transcribe'`

- [ ] **Step 3: 프롬프트**

`src/preprocessing/prompts.py`:

```python
"""전처리 단계 LLM 프롬프트. 코드와 분리해 변경 이력을 따로 볼 수 있게 한다.
프롬프트가 바뀌면 캐시 키가 바뀌어 해당 단계만 다시 호출된다 (ADR-0014)."""

TRANSCRIBE_SYSTEM = """당신은 OCR 엔진입니다. 채용공고 이미지(또는 세로로 자른 일부)를 받습니다.
규칙:
- 이미지에 보이는 글자를 '그대로' 옮겨 적으세요. 요약·해석·보정·번역을 하지 마세요.
- 읽기 순서는 위→아래, 왼쪽→오른쪽입니다. 여러 단으로 나뉜 영역은 단 순서대로 적으세요.
- 표는 마크다운 표('| 열1 | 열2 |')로 적으세요. 병합된 셀은 해당하는 모든 행에 같은 값을 반복해서 채우세요.
- 섹션 제목은 앞에 '## '를 붙이세요.
- 장식 그래픽·로고·QR 코드는 무시하세요.
- 직전 조각의 마지막 줄이 주어지면, 그와 겹치는 줄은 다시 적지 마세요.
- 글자가 없으면 빈 문자열만 출력하세요."""

STRUCTURE_SYSTEM = """당신은 채용공고를 구조화하는 분석가입니다. 이미지에서 전사된 공고 텍스트를 받아
지원자 매칭에 쓸 조건으로 바꿉니다. 직군은 무엇이든 될 수 있습니다(사무·생산·의료·영업·개발 등).

requirements — 지원자가 갖춰야 하거나 우대받는 조건:
- 하나의 판정 가능한 조건 단위로 나누세요. 서로 다른 조건이 "및"으로 묶여 있으면 나누세요.
- priority: 자격요건·지원자격·필수 → must, 우대·우대사항 → preferred. 목록 안의 '우대' 하위 항목도 preferred입니다.
- category: experience(경력·근무경험), education(학력·전공), certification(자격증·면허),
  language(어학), skill(도구·기술 숙련), domain_knowledge(업무 지식),
  soft_skill(성향·태도), other(그 외: 근무 가능 조건, 거주지, 병역, 해외여행 결격 여부 등).
- positions: 모집분야가 여럿이고 특정 분야에만 해당하는 요건이면 그 분야 이름들을, 모든 분야에 해당하면 빈 목록.
  모집분야 표에 분야별 조건(전공 등)이 있으면 조건마다 요건을 만들고 해당 분야들을 positions에 나열하세요.
  같은 조건이 여러 분야에 해당하면 요건 하나로 만드세요.
- min_years: 경력 연차가 명시되면 숫자로. min_education: 학력 하한(none/high_school/associate/bachelor/master/phd).
- sensitive: 국가보훈·장애인 등 법령에 따른 우대 항목이면 true.
- quote: 근거가 된 전사 텍스트의 줄을 '그대로' 복사하세요. 표라면 해당 행 전체를 복사하세요.
- 요건으로 만들지 않는 것: "경력 무관"·"전공 무관"처럼 조건이 없음을 뜻하는 문구,
  채용 결격 사유(피성년후견인·형 집행 등 법정 결격 조건), 근무조건, 전형절차, 제출서류, 복리후생, 문의처.

positions — 모집분야 목록 (name, 상위 분류 group, 세부 직무 duties, 근무지 location).
conditions — 고용형태, 근무지 목록, 근무 요일·시간·교대, 그 외 근무조건.
title·company·job_family — 이미지에 적힌 공고명·회사명, 직군(자유 텍스트).

전사 텍스트에 없는 내용은 만들지 마세요."""
```

- [ ] **Step 4: 구현**

`src/preprocessing/transcribe.py`:

```python
"""조각 이미지 → 원문 전사 (ADR-0010, ADR-0011).

조각 경계를 주석으로 남겨, 구조화 결과의 근거를 원본 이미지 위치까지 거슬러 올라갈 수 있게 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from llm import LLM

from .prompts import TRANSCRIBE_SYSTEM

MARK = "<!-- slice {index:02d} image={image} part={part} -->"
MARK_RE = re.compile(r"<!-- slice (\d+) image=(\d+) part=(\d+) -->")
TAIL_LINES = 3


@dataclass(frozen=True)
class SliceRef:
    path: Path
    image_index: int   # 스냅샷 이미지 번호
    part: int          # 그 이미지 안에서 몇 번째 조각


def transcribe(llm: LLM, slices: list[SliceRef], *, model: str, posting_id: str) -> str:
    parts: list[str] = []
    tail = ""
    for i, ref in enumerate(slices):
        user_text = f"직전 조각의 마지막 줄:\n{tail}" if tail else None
        text = llm.vision_text(model=model, system=TRANSCRIBE_SYSTEM, image=ref.path,
                               user_text=user_text, tag=f"transcribe-{posting_id}-{i:02d}").strip()
        parts.append(MARK.format(index=i, image=ref.image_index, part=ref.part) + "\n" + text)
        tail = "\n".join(text.splitlines()[-TAIL_LINES:])
    return "\n\n".join(parts)


def slice_at(transcript: str, offset: int) -> tuple[Optional[int], Optional[int]]:
    """offset 위치를 포함하는 조각의 (이미지 번호, 조각 번호)."""
    found: tuple[Optional[int], Optional[int]] = (None, None)
    for m in MARK_RE.finditer(transcript):
        if m.start() > offset:
            break
        found = (int(m.group(2)), int(m.group(1)))
    return found
```

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/test_transcribe.py -v`
Expected: 2 passed

- [ ] **Step 6: 커밋**

```bash
git add src/preprocessing/prompts.py src/preprocessing/transcribe.py tests/test_transcribe.py
git commit -m "feat(preprocessing): 조각별 비전 전사와 조각 경계 주석 (ADR-0011)"
```

---

### Task 7: 구조화

**Files:**
- Create: `src/preprocessing/structure.py`
- Test: `tests/test_structure.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from openai.lib._pydantic import to_strict_json_schema  # OpenAI strict 스키마 호환성 확인용

from preprocessing.structure import StructuredPosting, structure

from .fakes import FakeLLM

EMPTY = StructuredPosting.model_validate({
    "title": "t", "company": None, "job_family": "f", "positions": [], "requirements": [],
    "conditions": {"employment_type": None, "locations": [], "schedule": None, "others": []},
})


def test_structure_sends_whole_transcript_once():
    seen = {}

    def respond(user):
        seen["user"] = user
        return EMPTY

    llm = FakeLLM(structured=[respond])
    assert structure(llm, "## 지원자격\n- 고졸 이상", model="t", posting_id="55") == EMPTY
    assert "## 지원자격\n- 고졸 이상" in seen["user"]
    assert llm.calls == [("structured", "structure-55")]


def test_llm_output_schema_is_openai_strict_compatible():
    schema = to_strict_json_schema(StructuredPosting)
    assert schema["additionalProperties"] is False
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_structure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'preprocessing.structure'`

- [ ] **Step 3: 구현**

`src/preprocessing/structure.py`:

```python
"""전사 텍스트 → 구조화 (텍스트 LLM, Structured Output) (ADR-0011).

여기 정의한 스키마는 LLM 출력 전용이다. OpenAI strict 모드를 위해 기본값 없이 모든 필드를 명시한다.
id 부여·인용 검증·중복 병합은 verify.py(코드)가 한다.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from llm import LLM

from .criteria import Category, EducationLevel, Priority
from .prompts import STRUCTURE_SYSTEM


class LLMRequirement(BaseModel):
    text: str
    normalized: str
    priority: Priority
    category: Category
    positions: list[str]
    min_years: Optional[float]
    min_education: Optional[EducationLevel]
    sensitive: bool
    quote: str


class LLMPosition(BaseModel):
    name: str
    group: Optional[str]
    duties: Optional[str]
    location: Optional[str]


class LLMConditions(BaseModel):
    employment_type: Optional[str]
    locations: list[str]
    schedule: Optional[str]
    others: list[str]


class StructuredPosting(BaseModel):
    title: str
    company: Optional[str]
    job_family: str
    positions: list[LLMPosition]
    requirements: list[LLMRequirement]
    conditions: LLMConditions


def structure(llm: LLM, transcript: str, *, model: str, posting_id: str) -> StructuredPosting:
    """전사 전체를 한 번에 구조화한다 (조각 단위로 하면 섹션 제목과 항목이 갈라진다)."""
    return llm.structured(
        model=model,
        system=STRUCTURE_SYSTEM,
        user=f"## 전사된 공고 텍스트\n\n{transcript}",
        schema=StructuredPosting,
        tag=f"structure-{posting_id}",
    )
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_structure.py -v`
Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add src/preprocessing/structure.py tests/test_structure.py
git commit -m "feat(preprocessing): 전사 전체를 한 번에 구조화 (Structured Output 스키마)"
```

---

### Task 8: 검증·후처리

**Files:**
- Create: `src/preprocessing/verify.py`
- Test: `tests/test_verify.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from preprocessing.criteria import CriteriaSource
from preprocessing.structure import LLMConditions, LLMPosition, LLMRequirement, StructuredPosting
from preprocessing.verify import build_criteria, find_quote

TRANSCRIPT = (
    "<!-- slice 00 image=0 part=0 -->\n## 지원자격\n- 고등학교 졸업 이상\n- 야간근무 가능\n\n"
    "<!-- slice 01 image=0 part=1 -->\n## 우대사항\n- 해당직무 근무경험자\n- 국가보훈대상자"
)
SRC = CriteriaSource(site="saramin", posting_id="55", snapshot_fetched_at="t0", image_sha256=["abc"])


def llm_req(text, priority="must", category="other", quote=None, positions=(), sensitive=False):
    return LLMRequirement(text=text, normalized=text, priority=priority, category=category,
                          positions=list(positions), min_years=None, min_education=None,
                          sensitive=sensitive, quote=text if quote is None else quote)


def build(reqs, positions=()):
    out = StructuredPosting(
        title="생산직 채용", company="OO", job_family="식품 생산", positions=list(positions),
        requirements=list(reqs),
        conditions=LLMConditions(employment_type="정규직", locations=["청주"], schedule="주 5일", others=[]),
    )
    return build_criteria(out, TRANSCRIPT, source=SRC, models={"transcribe": "v", "structure": "t"},
                          extracted_at="t1")


def test_find_quote_ignores_whitespace_differences():
    assert find_quote("- 고등학교  졸업\n이상", TRANSCRIPT) == TRANSCRIPT.index("- 고등학교")
    assert find_quote("대학교 졸업", TRANSCRIPT) is None
    assert find_quote(" ", TRANSCRIPT) is None


def test_ids_evidence_location_and_missing_quote_flag():
    c = build([
        llm_req("고등학교 졸업 이상", category="education", quote="- 고등학교 졸업 이상"),
        llm_req("해당직무 근무경험", "preferred", "experience", quote="- 해당직무 근무경험자"),
        llm_req("운전면허", quote="- 1종 보통 운전면허"),                    # 전사에 없는 인용
    ])
    assert [r.id for r in c.requirements] == ["r1", "r2", "r3"]
    assert [(r.evidence.image_index, r.evidence.slice_index) for r in c.requirements] == [
        (0, 0), (0, 1), (None, None)]
    assert c.requirements[2].flags == ["quote_not_found"]
    assert c.warnings == ["근거 인용을 전사에서 찾지 못함: r3"]
    assert c.suitable


def test_duplicates_merge_keeping_must_but_different_positions_stay_separate():
    c = build([
        llm_req("야간근무 가능", "preferred"),
        llm_req("야간근무  가능", "must"),                                  # 공백만 다른 중복
        llm_req("상경계열 우대", "preferred", "education", quote="- 고등학교 졸업 이상", positions=["재무"]),
        llm_req("상경계열 우대", "preferred", "education", quote="- 고등학교 졸업 이상", positions=["수급"]),
    ])
    assert [(r.id, r.text, r.priority, r.positions) for r in c.requirements] == [
        ("r1", "야간근무 가능", "must", []),
        ("r2", "상경계열 우대", "preferred", ["재무"]),
        ("r3", "상경계열 우대", "preferred", ["수급"]),
    ]


def test_no_requirements_means_unsuitable():
    c = build([])
    assert not c.suitable
    assert c.warnings == ["요건이 0개 — 이미지에 자격요건이 없는 공고(안내 배너 등)일 수 있음"]


def test_no_must_requirement_warns():
    c = build([llm_req("해당직무 근무경험", "preferred", quote="- 해당직무 근무경험자")])
    assert c.warnings == ["필수 요건이 없음 — 필수/우대 판별을 확인"]


def test_carries_sensitive_positions_and_conditions():
    c = build([llm_req("국가보훈대상자", "preferred", quote="- 국가보훈대상자", sensitive=True)],
              positions=[LLMPosition(name="생산직", group=None, duties="배합/성형/포장", location="청주")])
    assert c.requirements[0].sensitive is True
    assert c.positions[0].name == "생산직" and c.positions[0].duties == "배합/성형/포장"
    assert (c.conditions.employment_type, c.conditions.locations) == ("정규직", ["청주"])
    assert (c.title, c.company, c.job_family, c.source.posting_id) == ("생산직 채용", "OO", "식품 생산", "55")
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'preprocessing.verify'`

- [ ] **Step 3: 구현**

`src/preprocessing/verify.py`:

```python
"""구조화 결과의 검증·후처리 — LLM이 아니라 코드가 책임지는 부분 (ADR-0011).

- 근거 인용이 전사에 실제로 있는지 확인하고 출처 위치(이미지·조각)를 채운다
- 공백만 다른 중복 요건을 병합한다 (겹침 분할로 같은 줄이 두 번 전사될 수 있음)
- id를 순서대로 부여하고, 이상 징후를 경고로 남긴다
"""
from __future__ import annotations

import re
from typing import Optional

from .criteria import Conditions, CriteriaSource, EvidenceRef, PostingCriteria, Position, Requirement
from .structure import LLMRequirement, StructuredPosting
from .transcribe import slice_at

MAX_REQUIREMENTS = 30


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def find_quote(quote: str, transcript: str) -> Optional[int]:
    """공백을 무시하고 quote를 찾아, 전사 원문에서의 시작 위치를 돌려준다. 없으면 None."""
    needle = _compact(quote)
    if len(needle) < 2:
        return None
    positions = [i for i, ch in enumerate(transcript) if not ch.isspace()]
    haystack = "".join(transcript[i] for i in positions)
    found = haystack.find(needle)
    return None if found < 0 else positions[found]


def dedupe(requirements: list[LLMRequirement]) -> list[LLMRequirement]:
    """같은 유형·같은 모집분야에서 공백만 다른 요건은 하나로. 하나라도 must면 must. 순서 유지."""
    merged: dict[tuple, LLMRequirement] = {}
    for r in requirements:
        key = (r.category, _compact(r.text), tuple(sorted(r.positions)))
        if key in merged:
            if r.priority == "must":
                merged[key].priority = "must"
            continue
        merged[key] = r.model_copy()
    return list(merged.values())


def warnings_for(requirements: list[Requirement]) -> list[str]:
    if not requirements:
        return ["요건이 0개 — 이미지에 자격요건이 없는 공고(안내 배너 등)일 수 있음"]
    warnings = []
    if not any(r.priority == "must" for r in requirements):
        warnings.append("필수 요건이 없음 — 필수/우대 판별을 확인")
    if len(requirements) > MAX_REQUIREMENTS:
        warnings.append(f"요건이 {len(requirements)}개로 많음 — 요건 분리 과다 의심")
    missing = [r.id for r in requirements if "quote_not_found" in r.flags]
    if missing:
        warnings.append(f"근거 인용을 전사에서 찾지 못함: {', '.join(missing)}")
    return warnings


def build_criteria(out: StructuredPosting, transcript: str, *, source: CriteriaSource,
                   models: dict[str, str], extracted_at: str) -> PostingCriteria:
    requirements: list[Requirement] = []
    for i, r in enumerate(dedupe(out.requirements), start=1):
        offset = find_quote(r.quote, transcript)
        image_index, slice_index = slice_at(transcript, offset) if offset is not None else (None, None)
        requirements.append(Requirement(
            id=f"r{i}", text=r.text, normalized=r.normalized, priority=r.priority, category=r.category,
            positions=r.positions, min_years=r.min_years, min_education=r.min_education, sensitive=r.sensitive,
            evidence=EvidenceRef(quote=r.quote, image_index=image_index, slice_index=slice_index),
            flags=[] if offset is not None else ["quote_not_found"],
        ))
    return PostingCriteria(
        source=source, extracted_at=extracted_at, models=models,
        title=out.title, company=out.company, job_family=out.job_family,
        positions=[Position(**p.model_dump()) for p in out.positions],
        requirements=requirements,
        conditions=Conditions(**out.conditions.model_dump()),
        suitable=bool(requirements),
        warnings=warnings_for(requirements),
    )
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_verify.py -v`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add src/preprocessing/verify.py tests/test_verify.py
git commit -m "feat(preprocessing): 인용 검증·출처 위치·중복 병합·경고 (코드가 책임지는 후처리)"
```

---

### Task 9: 전처리 서비스

**Files:**
- Create: `src/preprocessing/service.py`
- Test: `tests/test_preprocessing_service.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from crawler.snapshot import PostingSnapshot, SourceRef, StoredImage, save_file, save_snapshot, snapshot_dir
from preprocessing.criteria import criteria_dir, load_criteria
from preprocessing.service import extract
from preprocessing.structure import LLMConditions, LLMRequirement, StructuredPosting
from settings import Settings

from .fakes import FakeLLM

STRUCTURED = StructuredPosting(
    title="생산직 채용", company="OO", job_family="식품 생산", positions=[],
    requirements=[LLMRequirement(text="고등학교 졸업 이상", normalized="고졸 이상", priority="must",
                                 category="education", positions=[], min_years=None,
                                 min_education="high_school", sensitive=False, quote="- 고등학교 졸업 이상")],
    conditions=LLMConditions(employment_type=None, locations=[], schedule=None, others=[]),
)
VISION = ["## 지원자격\n- 고등학교 졸업 이상"] + [f"- 기타 {i}" for i in range(9)]


def poster_bytes(height, width=720):
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    for y in range(20, height - 40, 80):
        for x in range(10, width - 10, 12):
            draw.rectangle([x, y, x + 7, y + 30], fill="black")
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def make_snapshot(data_dir, heights=(1890,), with_html=True):
    d = snapshot_dir(data_dir, "saramin", "55")
    images = []
    for i, h in enumerate(heights):
        f = save_file(d, f"images/{i:02d}.png", poster_bytes(h))
        images.append(StoredImage(**f.model_dump(), index=i, source_url=f"https://img/{i}.png",
                                  format="PNG", width=720, height=h))
    snap = PostingSnapshot(
        source=SourceRef(site="saramin", posting_id="55", url="u"),
        fetched_at="2026-10-12T00:00:00+00:00",
        title="표시용 페이지 제목",
        view_html=save_file(d, "view.html", b"<title>page</title>"),
        detail_html=save_file(d, "detail.html", "<td style='font-size:0'>숨김: 회계 영업</td>".encode()),
        images=images, body_text_length=0, is_image_posting=bool(images),
    )
    save_snapshot(d, snap)
    if not with_html:
        (d / "view.html").unlink()
        (d / "detail.html").unlink()
    return snap


def settings(data_dir, slice_height=1000):
    return Settings(data_dir=data_dir, vision_model="v", text_model="t", slice_height=slice_height)


def test_extract_writes_slices_transcript_and_criteria(tmp_path):
    snap = make_snapshot(tmp_path)
    llm = FakeLLM(vision=list(VISION), structured=[STRUCTURED])
    c = extract("55", settings(tmp_path), llm=llm)

    out = criteria_dir(tmp_path, "saramin", "55")
    slices = sorted((out / "slices").glob("*.png"))
    vision_calls = [tag for kind, tag in llm.calls if kind == "vision"]
    assert len(slices) == len(vision_calls) >= 2                     # 1890px → 1000px 목표로 분할
    assert llm.calls[-1] == ("structured", "structure-55")
    assert (out / "transcript.md").read_text(encoding="utf-8").startswith("<!-- slice 00 image=0 part=0 -->")
    assert c.title == "생산직 채용"                                   # 이미지에서 읽은 제목 (페이지 제목 아님)
    assert c.requirements[0].evidence.slice_index == 0 and c.requirements[0].flags == []
    assert c.source.image_sha256 == [i.sha256 for i in snap.images]
    assert c.models == {"transcribe": "v", "structure": "t"}
    assert load_criteria(out) == c


def test_html_is_never_read(tmp_path):
    """ADR-0008: 스냅샷의 HTML을 지워도 결과가 같다."""
    make_snapshot(tmp_path / "a")
    with_html = extract("55", settings(tmp_path / "a"), llm=FakeLLM(vision=list(VISION), structured=[STRUCTURED]))
    make_snapshot(tmp_path / "b", with_html=False)
    without_html = extract("55", settings(tmp_path / "b"), llm=FakeLLM(vision=list(VISION), structured=[STRUCTURED]))
    assert with_html.model_dump(exclude={"extracted_at"}) == without_html.model_dump(exclude={"extracted_at"})


def test_slice_height_zero_sends_each_image_whole(tmp_path):
    make_snapshot(tmp_path, heights=(1890, 900))
    llm = FakeLLM(vision=list(VISION), structured=[STRUCTURED])
    extract("55", settings(tmp_path, slice_height=0), llm=llm)
    assert [tag for kind, tag in llm.calls if kind == "vision"] == ["transcribe-55-00", "transcribe-55-01"]


def test_second_extract_reuses_result_without_llm(tmp_path):
    make_snapshot(tmp_path)
    first = extract("55", settings(tmp_path), llm=FakeLLM(vision=list(VISION), structured=[STRUCTURED]))
    idle = FakeLLM()
    assert extract("55", settings(tmp_path), llm=idle) == first
    assert idle.calls == []


def test_refresh_extracts_again(tmp_path):
    make_snapshot(tmp_path)
    extract("55", settings(tmp_path), llm=FakeLLM(vision=list(VISION), structured=[STRUCTURED]))
    again = FakeLLM(vision=list(VISION), structured=[STRUCTURED])
    extract("55", settings(tmp_path), llm=again, refresh=True)
    assert again.calls[-1] == ("structured", "structure-55")


def test_missing_snapshot_raises_with_hint(tmp_path):
    with pytest.raises(RuntimeError, match="jobfit crawl 55"):
        extract("55", settings(tmp_path), llm=FakeLLM())


def test_snapshot_without_images_is_unsuitable_and_calls_no_llm(tmp_path):
    make_snapshot(tmp_path, heights=())
    idle = FakeLLM()
    c = extract("55", settings(tmp_path), llm=idle)
    assert not c.suitable and c.warnings == ["스냅샷에 본문 이미지가 없음"]
    assert idle.calls == []


def test_failure_leaves_no_criteria(tmp_path):
    make_snapshot(tmp_path)

    def boom(user):
        raise RuntimeError("API 오류")

    with pytest.raises(RuntimeError, match="API 오류"):
        extract("55", settings(tmp_path), llm=FakeLLM(vision=list(VISION), structured=[boom]))
    assert load_criteria(criteria_dir(tmp_path, "saramin", "55")) is None
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_preprocessing_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'preprocessing.service'`

- [ ] **Step 3: 구현**

`src/preprocessing/service.py`:

```python
"""전처리 서비스. CLI·API가 공통으로 호출한다 (ADR-0002).

입력은 공고 스냅샷의 **이미지뿐**이다. HTML(view.html, detail.html)은 읽지 않는다 (ADR-0008).
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from PIL import Image

from crawler.saramin import parse_rec_idx
from crawler.service import SITE
from crawler.snapshot import PostingSnapshot, load_snapshot, snapshot_dir
from llm import LLM
from settings import Settings

from .criteria import CRITERIA_FILE, CriteriaSource, PostingCriteria, criteria_dir, load_criteria, save_criteria
from .images import slice_image
from .structure import structure
from .transcribe import SliceRef, transcribe
from .verify import build_criteria

TRANSCRIPT_FILE = "transcript.md"

Log = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def prepare_slices(snapshot: PostingSnapshot, snap_dir: Path, out_dir: Path, settings: Settings) -> list[SliceRef]:
    """스냅샷 이미지 → 정규화·분할한 조각 PNG (out_dir/slices/{이미지}_{조각}.png)."""
    slices_dir = out_dir / "slices"
    shutil.rmtree(slices_dir, ignore_errors=True)
    slices_dir.mkdir(parents=True)
    refs: list[SliceRef] = []
    for image in snapshot.images:
        with Image.open(snap_dir / image.path) as im:
            pieces = slice_image(im, max_width=settings.max_width, target_height=settings.slice_height)
        for part, piece in enumerate(pieces):
            path = slices_dir / f"{image.index:02d}_{part:02d}.png"
            piece.save(path)
            refs.append(SliceRef(path=path, image_index=image.index, part=part))
    return refs


def extract(ref: str, settings: Settings, *, llm: LLM, refresh: bool = False, log: Log = _noop) -> PostingCriteria:
    """공고 1건의 조건을 추출해 data/criteria/{site}/{id}/에 저장한다. 결과가 있으면 재사용한다."""
    posting_id = parse_rec_idx(ref)
    snap_dir = snapshot_dir(settings.data_dir, SITE, posting_id)
    snapshot = load_snapshot(snap_dir)
    if snapshot is None:
        raise RuntimeError(f"공고 스냅샷이 없습니다 — 먼저 `jobfit crawl {posting_id}`를 실행하세요")

    out_dir = criteria_dir(settings.data_dir, SITE, posting_id)
    existing = load_criteria(out_dir)
    if existing is not None and not refresh:
        log(f"[extract] 기존 결과 재사용: {out_dir}")
        return existing
    (out_dir / CRITERIA_FILE).unlink(missing_ok=True)   # 실패하면 결과가 남지 않게 먼저 지운다

    source = CriteriaSource(site=SITE, posting_id=posting_id, snapshot_fetched_at=snapshot.fetched_at,
                            image_sha256=[i.sha256 for i in snapshot.images])
    models = {"transcribe": settings.vision_model, "structure": settings.text_model}
    extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not snapshot.images:
        criteria = PostingCriteria(source=source, extracted_at=extracted_at, models=models, title="",
                                   job_family="", suitable=False, warnings=["스냅샷에 본문 이미지가 없음"])
    else:
        slices = prepare_slices(snapshot, snap_dir, out_dir, settings)
        log(f"[extract] 공고 {posting_id}: 이미지 {len(snapshot.images)}장 → 조각 {len(slices)}개 전사")
        transcript = transcribe(llm, slices, model=settings.vision_model, posting_id=posting_id)
        (out_dir / TRANSCRIPT_FILE).write_text(transcript, encoding="utf-8")
        log(f"[extract] 구조화 ({settings.text_model})")
        structured = structure(llm, transcript, model=settings.text_model, posting_id=posting_id)
        criteria = build_criteria(structured, transcript, source=source, models=models, extracted_at=extracted_at)

    save_criteria(out_dir, criteria)
    for warning in criteria.warnings:
        log(f"[extract] 경고: {warning}")
    return criteria
```

- [ ] **Step 4: 통과 확인**

Run: `pytest -q`
Expected: 전부 PASS (`tests/test_preprocessing_service.py` 8 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/preprocessing/service.py tests/test_preprocessing_service.py
git commit -m "feat(preprocessing): 전처리 서비스 — 이미지만 입력, 결과 재사용, 실패 시 결과 없음"
```

---

### Task 10: CLI — extract / criteria / models

**Files:**
- Modify: `src/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_cli.py`에 추가:

```python
from preprocessing import service as preprocessing_service
from preprocessing.criteria import (
    CriteriaSource, EvidenceRef, PostingCriteria, Position, Requirement, criteria_dir, save_criteria,
)


def sample_criteria():
    return PostingCriteria(
        source=CriteriaSource(site="saramin", posting_id="55", snapshot_fetched_at="t0", image_sha256=["a"]),
        extracted_at="t1", models={"transcribe": "v", "structure": "t"},
        title="생산직 채용", job_family="식품 생산", positions=[Position(name="생산직")],
        requirements=[
            Requirement(id="r1", text="고졸 이상", normalized="고졸", priority="must", category="education",
                        evidence=EvidenceRef(quote="- 고졸 이상", image_index=0, slice_index=0)),
            Requirement(id="r2", text="보훈", normalized="보훈", priority="preferred", category="other",
                        sensitive=True, evidence=EvidenceRef(quote="- 보훈"), flags=["quote_not_found"]),
        ],
        suitable=True, warnings=["근거 인용을 전사에서 찾지 못함: r2"],
    )


def test_extract_command_uses_cached_llm_and_prints_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    seen = []

    def fake_extract(ref, settings, *, llm, refresh, log):
        seen.append((ref, refresh, type(llm).__name__, settings.data_dir))
        return sample_criteria()

    monkeypatch.setattr(preprocessing_service, "extract", fake_extract)
    result = CliRunner().invoke(cli.app, ["extract", "55", "--refresh"])
    assert result.exit_code == 0, result.output
    assert seen == [("55", True, "CachedLLM", tmp_path)]
    assert "55  요건 2개 (필수 1, 우대 1)  모집분야 1  ⚠ 1  생산직 채용" in result.output


def test_criteria_command_shows_requirements_and_warnings(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    save_criteria(criteria_dir(tmp_path, "saramin", "55"), sample_criteria())
    result = CliRunner().invoke(cli.app, ["criteria", "55"])
    assert result.exit_code == 0, result.output
    for text in ("r1", "고졸 이상", "img0/slice0", "r2", "⚠ 근거 인용을 전사에서 찾지 못함: r2"):
        assert text in result.output


def test_criteria_command_without_result_exits_1(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(cli.app, ["criteria", "55"])
    assert result.exit_code == 1
    assert "jobfit extract 55" in result.output
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — 새 테스트 3개 (`No such command 'extract'` / `'criteria'`)

- [ ] **Step 3: 구현**

`src/cli.py` import에 추가 (`from crawler import service` 위):

```python
from crawler.saramin import parse_rec_idx
from llm import CachedLLM, OpenAILLM
from preprocessing import service as preprocessing_service
from preprocessing.criteria import criteria_dir, load_criteria
```

`src/cli.py` 끝에 추가:

```python
def make_llm(settings) -> CachedLLM:
    """응답 캐시(ADR-0014)를 거치는 OpenAI 클라이언트. 캐시 적중이면 API 키가 없어도 된다."""
    return CachedLLM(OpenAILLM, settings.llm_cache_dir)


@app.command()
def extract(
    refs: List[str] = typer.Argument(..., help="사람인 공고 URL 또는 rec_idx (여러 개 가능)"),
    refresh: bool = typer.Option(False, "--refresh", help="기존 추출 결과를 무시하고 다시 추출"),
):
    """공고 스냅샷의 이미지에서 조건을 추출해 data/criteria/에 저장."""
    settings = load_settings()
    llm = make_llm(settings)
    for ref in refs:
        c = preprocessing_service.extract(ref, settings, llm=llm, refresh=refresh, log=_log)
        must = sum(r.priority == "must" for r in c.requirements)
        status = "" if c.suitable else "  [red]부적합[/red]"
        console.print(f"{c.source.posting_id}  요건 {len(c.requirements)}개 (필수 {must}, "
                      f"우대 {len(c.requirements) - must})  모집분야 {len(c.positions)}  "
                      f"⚠ {len(c.warnings)}  {c.title}{status}")


@app.command()
def criteria(ref: str = typer.Argument(..., help="rec_idx 또는 URL")):
    """추출된 공고 조건을 표로 보여준다."""
    settings = load_settings()
    posting_id = parse_rec_idx(ref)
    c = load_criteria(criteria_dir(settings.data_dir, "saramin", posting_id))
    if c is None:
        console.print(f"[red]추출 결과가 없습니다 — 먼저 `jobfit extract {posting_id}`를 실행하세요[/red]")
        raise typer.Exit(1)
    console.rule(f"{c.title} ({c.job_family})")
    table = Table("id", "구분", "유형", "요건", "모집분야", "근거")
    for r in c.requirements:
        where = (f"img{r.evidence.image_index}/slice{r.evidence.slice_index}"
                 if r.evidence.slice_index is not None else "✗ 없음")
        kind = ("필수" if r.priority == "must" else "우대") + (" ⚑" if r.sensitive else "")
        table.add_row(r.id, kind, r.category, r.text, ", ".join(r.positions) or "전체", where)
    console.print(table)
    if c.positions:
        console.print("모집분야: " + ", ".join(p.name for p in c.positions))
    cond = c.conditions
    parts = [x for x in [cond.employment_type, cond.schedule, *cond.locations, *cond.others] if x]
    if parts:
        console.print("근무조건(점수 미반영): " + " · ".join(parts))
    for warning in c.warnings:
        console.print(f"[yellow]⚠ {warning}[/yellow]")


@app.command()
def models():
    """현재 API 키로 사용 가능한 모델 목록 (OPENAI_API_KEY 필요)."""
    load_settings()  # .env 로드
    for name in OpenAILLM().list_models():
        console.print(name)
```

- [ ] **Step 4: 통과 확인**

```bash
pytest tests/test_cli.py -v
jobfit --help
```
Expected: 5 passed, 도움말에 `extract`, `criteria`, `models`

- [ ] **Step 5: 커밋**

```bash
git add src/cli.py tests/test_cli.py
git commit -m "feat(cli): jobfit extract / criteria / models"
```

---

### Task 11: 평가 도구와 정답 목록

**Files:**
- Create: `src/preprocessing/evaluate.py`, `tests/fixtures/criteria_truth/55189170.yaml`, `tests/fixtures/criteria_truth/55162188.yaml`
- Modify: `src/cli.py`
- Test: `tests/test_evaluate.py`, `tests/test_cli.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_evaluate.py`:

```python
from pathlib import Path

from preprocessing.criteria import CriteriaSource, EvidenceRef, PostingCriteria, Requirement
from preprocessing.evaluate import Truth, TruthItem, evaluate, load_truth, similarity

TRUTH_DIR = Path(__file__).parent / "fixtures" / "criteria_truth"


def R(rid, text, priority="must", category="other", normalized=None):
    return Requirement(id=rid, text=text, normalized=normalized or text, priority=priority, category=category,
                       evidence=EvidenceRef(quote=text))


def crit(*reqs):
    return PostingCriteria(
        source=CriteriaSource(site="saramin", posting_id="55", snapshot_fetched_at="t0", image_sha256=[]),
        extracted_at="t1", models={}, title="t", job_family="f", requirements=list(reqs), suitable=bool(reqs),
    )


def T(text, priority="must", category="other", aliases=()):
    return TruthItem(text=text, priority=priority, category=category, aliases=list(aliases))


def test_similarity_ignores_spacing_and_punctuation_but_not_short_fragments():
    assert similarity("고등학교 졸업 이상", "고등학교 졸업이상") == 1.0
    assert similarity("야간근무 가능", "야간 근무 가능자") == 1.0       # 충분히 긴 포함 관계
    assert similarity("영어", "영어 회화 능통자") < 0.6                 # 짧은 조각은 포함으로 치지 않음


def test_evaluate_counts_matches_misses_extras_and_agreement():
    truth = Truth(posting_id="55", requirements=[
        T("고등학교 졸업 이상", "must", "education"),
        T("야간근무 가능", "must", "other"),
        T("인근거주자", "preferred", "other"),
    ])
    ev = evaluate(truth, crit(
        R("r1", "고등학교 졸업 이상", "must", "education"),
        R("r2", "야간 근무 가능자", "preferred", "other"),     # 필수/우대 불일치
        R("r3", "운전면허", "must", "certification"),          # 정답에 없음
    ))
    assert [(t.text, r.id) for t, r in ev.matched] == [("고등학교 졸업 이상", "r1"), ("야간근무 가능", "r2")]
    assert [t.text for t in ev.missed] == ["인근거주자"]
    assert [r.id for r in ev.extra] == ["r3"]
    assert (ev.recall, ev.precision, ev.must_recall) == (2 / 3, 2 / 3, 1.0)
    assert (ev.priority_agreement, ev.category_agreement) == (0.5, 1.0)


def test_aliases_are_used_for_matching():
    truth = Truth(posting_id="55", requirements=[T("장애인은 관련법에 의거 우대", "preferred",
                                                     aliases=["장애인 우대"])])
    ev = evaluate(truth, crit(R("r1", "장애인 우대", "preferred")))
    assert ev.recall == 1.0


def test_empty_cases():
    ev = evaluate(Truth(posting_id="55", requirements=[]), crit())
    assert (ev.recall, ev.precision, ev.must_recall) == (1.0, 1.0, 1.0)


def test_truth_fixtures_are_valid():
    files = sorted(TRUTH_DIR.glob("*.yaml"))
    assert [f.stem for f in files] == ["55162188", "55189170"]
    for f in files:
        truth = load_truth(f)
        assert truth.posting_id == f.stem
        assert any(t.priority == "must" for t in truth.requirements)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_evaluate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'preprocessing.evaluate'`

- [ ] **Step 3: 구현**

`src/preprocessing/evaluate.py`:

```python
"""추출 결과를 사람이 만든 정답 요건 목록과 비교한다 (스펙 02 실험 X1–X3).

평가 전용이다 — 파이프라인은 정답을 읽지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .criteria import Category, PostingCriteria, Priority, Requirement

MATCH_THRESHOLD = 0.6
MIN_CONTAINMENT = 0.5   # 짧은 쪽이 긴 쪽 길이의 이 비율 이상일 때만 '포함'을 일치로 본다


class TruthItem(BaseModel):
    text: str
    priority: Priority
    category: Category
    positions: list[str] = Field(default_factory=list)
    sensitive: bool = False
    aliases: list[str] = Field(default_factory=list)


class Truth(BaseModel):
    posting_id: str
    requirements: list[TruthItem]


def load_truth(path: Path) -> Truth:
    return Truth.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text).lower()


def similarity(a: str, b: str) -> float:
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return 0.0
    short, long = sorted((ka, kb), key=len)
    if short in long and len(short) / len(long) >= MIN_CONTAINMENT:
        return 1.0
    return SequenceMatcher(None, ka, kb).ratio()


def _ratio(n: int, d: int) -> float:
    return n / d if d else 1.0


@dataclass
class Evaluation:
    matched: list[tuple[TruthItem, Requirement]]
    missed: list[TruthItem]
    extra: list[Requirement]

    @property
    def recall(self) -> float:
        return _ratio(len(self.matched), len(self.matched) + len(self.missed))

    @property
    def precision(self) -> float:
        return _ratio(len(self.matched), len(self.matched) + len(self.extra))

    @property
    def must_recall(self) -> float:
        must_matched = sum(t.priority == "must" for t, _ in self.matched)
        must_total = must_matched + sum(t.priority == "must" for t in self.missed)
        return _ratio(must_matched, must_total)

    @property
    def priority_agreement(self) -> float:
        return _ratio(sum(t.priority == r.priority for t, r in self.matched), len(self.matched))

    @property
    def category_agreement(self) -> float:
        return _ratio(sum(t.category == r.category for t, r in self.matched), len(self.matched))


def evaluate(truth: Truth, criteria: PostingCriteria, *, threshold: float = MATCH_THRESHOLD) -> Evaluation:
    """정답 항목마다 가장 비슷한 추출 요건 하나를 짝짓는다 (탐욕적, 1:1)."""
    remaining = list(criteria.requirements)
    matched: list[tuple[TruthItem, Requirement]] = []
    missed: list[TruthItem] = []
    for item in truth.requirements:
        names = [item.text, *item.aliases]
        best, best_score = None, 0.0
        for r in remaining:
            score = max(similarity(n, t) for n in names for t in (r.text, r.normalized, r.evidence.quote))
            if score > best_score:
                best, best_score = r, score
        if best is not None and best_score >= threshold:
            matched.append((item, best))
            remaining.remove(best)
        else:
            missed.append(item)
    return Evaluation(matched=matched, missed=missed, extra=remaining)
```

Run: `pytest tests/test_evaluate.py -v`
Expected: 4 passed, 1 failed (`test_truth_fixtures_are_valid` — 정답 파일 없음)

- [ ] **Step 4: 정답 목록 작성**

사람이 원본 이미지를 보고 작성한다. 평가 전용이며 파이프라인은 읽지 않는다.

`tests/fixtures/criteria_truth/55189170.yaml`:

```yaml
# 정답 요건 목록 — 사람이 공고 이미지를 보고 작성 (평가 전용, 파이프라인은 읽지 않는다)
# 공고: S-OIL 2026 사무직 신입사원 채용 (rec_idx 55189170)
posting_id: "55189170"
requirements:
  - text: 대학(원) 기졸업자 및 2027년 2월 이내 졸업 예정자
    priority: must
    category: education
  - text: 2027년 1월 입사가 가능한 자
    priority: must
    category: other
  - text: 공고 마감일 기준 유효한 공인영어성적(TOEIC, TOEFL, TOEIC Speaking, OPIc 등) 보유자
    priority: must
    category: language
  - text: 남성의 경우, 병역필 또는 군 면제자
    priority: must
    category: other
  - text: 해외여행에 결격사유가 없는 자
    priority: must
    category: other
  - text: 화공 전공
    priority: must
    category: education
    positions: [공정]
  - text: 기계/재료/금속/전기/전자 전공
    priority: must
    category: education
    positions: [설비기술]
  - text: 화공/안전/환경 전공
    priority: must
    category: education
    positions: [안전환경]
  - text: 상경계열 우대
    priority: preferred
    category: education
    positions: [경영전략, 경영지원, 영업/마케팅, 재무, 수급]
  - text: 장애인 및 보훈 대상자는 관계 법령에 의거하여 우대
    priority: preferred
    category: other
    sensitive: true
    aliases: [장애인 우대, 보훈 대상자 우대]
  - text: 영어 회화 능통자
    priority: preferred
    category: language
  - text: 엔지니어 직무 지원자의 경우, 직무 관련 자격증 소지자
    priority: preferred
    category: certification
    positions: [공정, 설비기술, 안전환경]
```

`tests/fixtures/criteria_truth/55162188.yaml`:

```yaml
# 정답 요건 목록 — 사람이 공고 이미지를 보고 작성 (평가 전용, 파이프라인은 읽지 않는다)
# 공고: ㈜오리온 청주공장 생산직 채용 (rec_idx 55162188)
posting_id: "55162188"
requirements:
  - text: 고등학교 졸업 이상
    priority: must
    category: education
  - text: 야간근무 가능
    priority: must
    category: other
  - text: 인근거주자
    priority: preferred
    category: other
  - text: 해당직무 근무경험자
    priority: preferred
    category: experience
  - text: 국가보훈대상자
    priority: preferred
    category: other
    sensitive: true
  - text: 장애인은 관련법에 의거 우대
    priority: preferred
    category: other
    sensitive: true
    aliases: [장애인 우대, 국가보훈대상자 및 장애인은 관련법에 의거 우대합니다]
```

Run: `pytest tests/test_evaluate.py -v`
Expected: 5 passed

- [ ] **Step 5: CLI 테스트 추가**

`tests/test_cli.py`에 추가:

```python
def test_evaluate_command_prints_metrics(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    save_criteria(criteria_dir(tmp_path, "saramin", "55"), sample_criteria())
    truth = tmp_path / "truth.yaml"
    truth.write_text('posting_id: "55"\nrequirements:\n'
                     '  - {text: 고졸 이상, priority: must, category: education}\n'
                     '  - {text: 인근거주자, priority: preferred, category: other}\n', encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["evaluate", "55", "--truth", str(truth)])
    assert result.exit_code == 0, result.output
    assert "재현율 50%" in result.output and "정밀도 50%" in result.output
    assert "누락: 인근거주자" in result.output and "추가: r2 보훈" in result.output
```

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `No such command 'evaluate'`

- [ ] **Step 6: CLI 구현**

`src/cli.py`: `from typing import List`를 `from pathlib import Path` + `from typing import List, Optional`로, `from settings import load_settings`를 `from settings import ROOT, load_settings`로 바꾸고 끝에 추가:

```python
@app.command()
def evaluate(
    ref: str = typer.Argument(..., help="rec_idx 또는 URL"),
    truth: Optional[Path] = typer.Option(None, "--truth", help="정답 파일 (기본: tests/fixtures/criteria_truth/{rec_idx}.yaml)"),
):
    """추출 결과를 사람이 만든 정답 요건 목록과 비교 (스펙 02 실험)."""
    from preprocessing.evaluate import evaluate as run_evaluation, load_truth

    settings = load_settings()
    posting_id = parse_rec_idx(ref)
    c = load_criteria(criteria_dir(settings.data_dir, "saramin", posting_id))
    if c is None:
        console.print(f"[red]추출 결과가 없습니다 — 먼저 `jobfit extract {posting_id}`를 실행하세요[/red]")
        raise typer.Exit(1)
    truth_path = truth or ROOT / "tests" / "fixtures" / "criteria_truth" / f"{posting_id}.yaml"
    ev = run_evaluation(load_truth(truth_path), c)
    console.print(f"{posting_id}  재현율 {ev.recall:.0%}  정밀도 {ev.precision:.0%}  필수 재현율 {ev.must_recall:.0%}  "
                  f"필수/우대 일치 {ev.priority_agreement:.0%}  유형 일치 {ev.category_agreement:.0%}")
    for t in ev.missed:
        console.print(f"  누락: {t.text}")
    for r in ev.extra:
        console.print(f"  추가: {r.id} {r.text}")
    for t, r in ev.matched:
        if t.priority != r.priority or t.category != r.category:
            console.print(f"  불일치: {r.id} {r.text} — 정답 {t.priority}/{t.category}, 추출 {r.priority}/{r.category}")
```

- [ ] **Step 7: 통과 확인**

Run: `pytest -q`
Expected: 76 passed

- [ ] **Step 8: 커밋**

```bash
git add src/preprocessing/evaluate.py src/cli.py tests/test_evaluate.py tests/test_cli.py tests/fixtures/criteria_truth
git commit -m "feat(preprocessing): 정답 대비 평가 도구(jobfit evaluate)와 공고 2건 정답 목록"
```

---

### Task 12: 실제 공고로 실행·실험 [수동 — OPENAI_API_KEY 필요]

**Files:**
- Create: `.env` (커밋 안 함), `data/criteria/…`, `data/cache/llm/…` (로컬)
- Modify: 스펙 02 11장, ADR-0010·0012 (기본값 확정), `src/settings.py` (기본 모델·분할 높이), `README.md`

- [ ] **Step 1: 정답 목록 검토 [수동]**

`tests/fixtures/criteria_truth/*.yaml`을 원본 이미지와 대조해 빠진 요건·잘못된 필수/우대·유형을 고친다.

- [ ] **Step 2: 키와 모델 확인**

```bash
cp .env.example .env      # OPENAI_API_KEY 입력
jobfit models | grep -E "gpt-4\.1|gpt-4o|gpt-5"
```
기본값(`gpt-4.1`, `gpt-4.1-mini`)이 목록에 없으면 `.env`의 `JOBFIT_VISION_MODEL`, `JOBFIT_TEXT_MODEL`을 목록에 있는 모델로.

- [ ] **Step 3: 첫 실행과 결과 검토**

```bash
jobfit extract 55162188 55189170
jobfit criteria 55162188
jobfit criteria 55189170
jobfit evaluate 55162188
jobfit evaluate 55189170
```
확인: `data/criteria/saramin/<ID>/slices/*.png`(조각), `transcript.md`(전사)를 원본과 대조한다.

- [ ] **Step 4: 실험 X1 — 분할 필요성**

```bash
for H in 0 1200 800; do
  JOBFIT_SLICE_HEIGHT=$H jobfit extract 55162188 55189170 --refresh
  JOBFIT_SLICE_HEIGHT=$H jobfit evaluate 55162188
  JOBFIT_SLICE_HEIGHT=$H jobfit evaluate 55189170
done
```
기록: 높이별 재현율·정밀도, 전사에서 숫자·고유명사 오독 수. 재현율이 같으면 조각이 적은 쪽.

- [ ] **Step 5: 실험 X2 — 모델**

X1에서 고른 높이로, 비전 모델을 상위/경량 2종으로 바꿔 같은 비교. 차이가 없으면 경량.

- [ ] **Step 6: 실험 X3 — 수용 기준 확인**

최종 설정에서 스펙 02 10장 수용 기준(필수 재현율 100%, 재현율·정밀도 ≥ 90%, 필수/우대 일치 100%, `quote_not_found` 0건)을 확인한다. 미달이면 원인(전사 / 구조화 프롬프트 / 정답 목록)을 분류해 고치고 다시 잰다.

- [ ] **Step 7: 실험 X4 (선택) — OCR 기준선**

`brew install tesseract tesseract-lang` 후 조각 이미지를 `tesseract <조각>.png - -l kor`로 전사해 비전 전사와 비교한다. 설치하지 않으면 건너뛰고 그 사실을 기록한다.

- [ ] **Step 8: 캐시 확인**

```bash
jobfit extract 55162188 55189170 --refresh   # 같은 설정 재실행
```
Expected: OpenAI 대시보드 기준 추가 호출 0건 (캐시 적중)

- [ ] **Step 9: 기록과 기본값 확정**

- 스펙 02 11장 표, ADR-0010(기본 모델)·ADR-0012(분할 높이) 갱신
- `src/settings.py`의 `DEFAULT_VISION_MODEL`, `DEFAULT_TEXT_MODEL`, `slice_height` 기본값 반영
- README에 `extract` / `criteria` / `evaluate` / `models` 사용법 추가

```bash
git add src/settings.py docs README.md tests/fixtures/criteria_truth
git commit -m "docs: 스펙 02 실험 결과와 전처리 기본값 확정"
```
