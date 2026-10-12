# 03. 지원자 매칭 스코어링 (scoring) 구현 계획

> **에이전트 작업자용:** 필수 하위 스킬 — `superpowers:executing-plans`(또는 `superpowers:subagent-driven-development`)로 태스크 단위로 실행한다. 단계는 체크박스(`- [ ]`)로 추적한다.

**스펙:** [2026-10-12-03-candidate-scoring-design.md](../specs/2026-10-12-03-candidate-scoring-design.md)

**목표:** `jobfit match <rec_idx>`가 `criteria.json`과 목업 이력서(`dataset/candidates/`)로 지원자별 0~100점·랭킹·요건별 근거를 만들어 `data/results/saramin/{rec_idx}/ranking.json`에 저장하고, `jobfit result`로 근거를 보여준다.

**아키텍처:** 이력서 모델·렌더링(`scoring/candidate.py`) → 판정(`judge.py`, LLM) → 인용 검증(`verify.py`) → 규칙 보정(`rules.py`) → 집계·설명(`score.py`, 순수 함수) → 저장(`result.py`). 오케스트레이션은 `scoring/service.py`. LLM은 기존 `llm.LLM` 프로토콜로 주입하고 테스트는 `tests/fakes.py`의 `FakeLLM`을 쓴다.

**기술 스택:** pydantic v2, openai(Structured Output, 기존 `llm.py`), Typer + rich, pytest. 새 의존성 없음.

**선행 조건:** 계획 02 완료 (`data/criteria/saramin/{55189170,55162188}/criteria.json`). 태스크 11(실제 실행)만 `OPENAI_API_KEY` 필요.

| # | 태스크 | 종류 | 의존 |
|---|---|---|---|
| 1 | 설정: 판정 모델 | TDD | — |
| 2 | 이력서 모델·로드·줄 번호 렌더링 | TDD | — |
| 3 | 결과 모델·가중치·저장 | TDD | — |
| 4 | 규칙: 학력 서열·경력 연수 | TDD | 2 |
| 5 | 집계·기여도·설명 | TDD | 3 |
| 6 | 판정 프롬프트·LLM 출력 스키마 | TDD | 2 |
| 7 | 판정 검증·규칙 보정 | TDD | 4, 6 |
| 8 | 스코어링 서비스 | TDD | 5, 7 |
| 9 | 목업 이력서 12건과 데이터셋 평가 도구 | TDD + 작성 | 2, 3 |
| 10 | CLI: match / result | TDD | 8, 9 |
| 11 | 실제 실행·실험 Y1–Y3 | 수동 (API 키) | 10 |
| 12 | 기록 | 문서 | 11 |

병렬 가능: [1], [2→4], [3→5], [2→6]을 동시에. 이후 [7→8], [9]는 2·3 이후 언제든. 그다음 [10→11→12].

---

### Task 1: 설정 — 판정 모델

**Files:**
- Modify: `src/settings.py`, `.env.example`, `README.md` (설정 표)
- Test: `tests/test_settings.py`

- [ ] **Step 1: 실패하는 테스트**

`tests/test_settings.py`의 `PREP_KEYS`에 `"JOBFIT_JUDGE_MODEL"`을 추가하고 테스트 추가:

```python
def test_judge_model_from_env_and_default(monkeypatch):
    for k in PREP_KEYS:
        monkeypatch.delenv(k, raising=False)
    assert load_settings(dotenv_path=None).judge_model == "gpt-4.1"
    monkeypatch.setenv("JOBFIT_JUDGE_MODEL", "j-model")
    assert load_settings(dotenv_path=None).judge_model == "j-model"
```

Run: `pytest tests/test_settings.py -q` → FAIL (`judge_model` 없음)

- [ ] **Step 2: 구현**

```python
DEFAULT_JUDGE_MODEL = "gpt-4.1"
# Settings
    judge_model: str = DEFAULT_JUDGE_MODEL      # 지원자 판정 (스펙 03)
# load_settings
        judge_model=env("JOBFIT_JUDGE_MODEL", DEFAULT_JUDGE_MODEL),
```

`.env.example`에 `# JOBFIT_JUDGE_MODEL=gpt-4.1`, README 설정 표에 한 줄.

Run: `pytest -q` → PASS. 커밋 `feat(settings): 판정 모델 설정`

---

### Task 2: 이력서 모델·로드·줄 번호 렌더링

**Files:**
- Create: `src/scoring/__init__.py`, `src/scoring/candidate.py`
- Test: `tests/test_candidate.py`

- [ ] **Step 1: 실패하는 테스트**

```python
import json

import pytest

from scoring.candidate import Candidate, load_candidates, render

BASE = {
    "id": "c1", "name": "김하늘", "headline": "경영학 전공 신입", "address": "서울 강서구",
    "desired_positions": ["재무"],
    "education": [{"level": "bachelor", "school": "한국대학교", "major": "경영학과",
                   "status": "graduated", "graduation": "2026-02"}],
    "experiences": [{"company": "가나상사", "role": "회계 인턴", "start": "2025-07", "end": "2025-12",
                     "description": "월 결산 보조"}],
    "certifications": [{"name": "전산회계 1급", "acquired": "2024-11"}],
    "languages": [{"language": "영어", "test": "TOEIC", "score": "915", "acquired": "2025-08"}],
    "military": "군필",
    "declarations": ["2027년 1월 입사 가능"],
    "skills": ["엑셀"],
    "self_intro": "첫 문단\n\n둘째 문단",
    "meta": {"target_posting": "55189170", "label": "perfect", "intent": "같은 단어로 충족",
             "expected": [{"requirement": "공인영어성적", "status": "met"}]},
}


def test_render_numbers_one_fact_per_line():
    lines = render(Candidate.model_validate(BASE)).splitlines()
    assert lines[0] == "L01 [기본] 김하늘 — 경영학 전공 신입"
    assert "L04 [학력] 학사 · 한국대학교 · 경영학과 · 졸업 (2026-02)" in lines
    assert any(l.endswith("[경력 1] 가나상사 · 회계 인턴 · 2025-07~2025-12") for l in lines)
    assert any(l.endswith("[경력 1 내용] 월 결산 보조") for l in lines)
    assert any(l.endswith("[자기 신고] 2027년 1월 입사 가능") for l in lines)
    assert [l.split(" ", 1)[1] for l in lines if "[자기소개]" in l] == ["[자기소개] 첫 문단", "[자기소개] 둘째 문단"]


def test_render_never_includes_meta():
    text = render(Candidate.model_validate(BASE))
    for secret in ("perfect", "55189170", "같은 단어로 충족", "expected"):
        assert secret not in text


def test_ongoing_job_and_optional_fields():
    c = Candidate.model_validate({**BASE, "address": None, "military": None,
                                  "experiences": [{"company": "A", "role": "B", "start": "2020-01", "end": None}]})
    text = render(c)
    assert "2020-01~재직 중" in text and "[주소]" not in text and "[병역]" not in text


def test_load_candidates_sorted_and_reports_bad_file(tmp_path):
    (tmp_path / "b.json").write_text(json.dumps({**BASE, "id": "b"}), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps({**BASE, "id": "a"}), encoding="utf-8")
    assert [c.id for c in load_candidates(tmp_path)] == ["a", "b"]
    (tmp_path / "z.json").write_text('{"id": "z"}', encoding="utf-8")
    with pytest.raises(ValueError, match="z.json"):
        load_candidates(tmp_path)


def test_duplicate_ids_rejected(tmp_path):
    for f in ("a.json", "b.json"):
        (tmp_path / f).write_text(json.dumps(BASE), encoding="utf-8")
    with pytest.raises(ValueError, match="중복"):
        load_candidates(tmp_path)
```

Run → FAIL (모듈 없음)

- [ ] **Step 2: 구현** — `src/scoring/candidate.py`

```python
"""지원자(목업 이력서) 모델과 줄 번호 렌더링 (ADR-0016).

render()가 이력서의 유일한 '원문'이다. 판정 LLM은 이 텍스트만 보고, 근거 인용도 이 텍스트에서 확인한다.
meta(의도 라벨 등)는 평가 전용이라 렌더링하지 않는다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

EducationLevel = Literal["high_school", "associate", "bachelor", "master", "phd"]
Status = Literal["met", "partial", "unmet", "unknown", "not_applicable"]

LEVEL_LABEL = {"high_school": "고등학교", "associate": "전문학사", "bachelor": "학사", "master": "석사", "phd": "박사"}
EDU_STATUS_LABEL = {"graduated": "졸업", "expected": "졸업 예정", "enrolled": "재학", "dropped": "중퇴"}


class Education(BaseModel):
    level: EducationLevel
    school: str
    major: Optional[str] = None
    status: Literal["graduated", "expected", "enrolled", "dropped"] = "graduated"
    graduation: Optional[str] = None          # "2026-02"


class Experience(BaseModel):
    company: str
    role: str
    start: str                                # "2021-03"
    end: Optional[str] = None                 # None = 재직 중
    description: str = ""


class Certification(BaseModel):
    name: str
    acquired: Optional[str] = None


class LanguageScore(BaseModel):
    language: str
    test: str
    score: str
    acquired: Optional[str] = None


class ExpectedJudgment(BaseModel):
    requirement: str                          # 요건 문구의 일부 ("공인영어성적")
    status: Status


class CandidateMeta(BaseModel):
    target_posting: str
    label: Literal["perfect", "partial", "mismatch"]
    intent: str = ""
    expected: list[ExpectedJudgment] = Field(default_factory=list)


class Candidate(BaseModel):
    id: str
    name: str
    headline: str = ""
    address: Optional[str] = None
    desired_positions: list[str] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[LanguageScore] = Field(default_factory=list)
    military: Optional[str] = None
    declarations: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    self_intro: str = ""
    meta: Optional[CandidateMeta] = None


def _dated(text: str, date: Optional[str]) -> str:
    return f"{text} ({date})" if date else text


def render_lines(c: Candidate) -> list[str]:
    lines = [f"[기본] {c.name} — {c.headline}" if c.headline else f"[기본] {c.name}"]
    if c.address:
        lines.append(f"[주소] {c.address}")
    if c.desired_positions:
        lines.append(f"[희망 분야] {', '.join(c.desired_positions)}")
    for e in c.education:
        parts = [LEVEL_LABEL[e.level], e.school] + ([e.major] if e.major else [])
        lines.append(f"[학력] {' · '.join(parts)} · {_dated(EDU_STATUS_LABEL[e.status], e.graduation)}")
    for i, x in enumerate(c.experiences, start=1):
        lines.append(f"[경력 {i}] {x.company} · {x.role} · {x.start}~{x.end or '재직 중'}")
        if x.description:
            lines.append(f"[경력 {i} 내용] {x.description}")
    lines += [f"[자격증] {_dated(x.name, x.acquired)}" for x in c.certifications]
    lines += [f"[어학] {_dated(f'{x.language} {x.test} {x.score}', x.acquired)}" for x in c.languages]
    if c.military:
        lines.append(f"[병역] {c.military}")
    lines += [f"[자기 신고] {d}" for d in c.declarations]
    if c.skills:
        lines.append(f"[기술] {', '.join(c.skills)}")
    lines += [f"[자기소개] {p.strip()}" for p in c.self_intro.splitlines() if p.strip()]
    return lines


def render(c: Candidate) -> str:
    return "\n".join(f"L{i:02d} {line}" for i, line in enumerate(render_lines(c), start=1))


def load_candidate(path: Path) -> Candidate:
    try:
        return Candidate.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as e:
        raise ValueError(f"{path.name}: 이력서 형식 오류\n{e}") from e


def load_candidates(directory: Path) -> list[Candidate]:
    if not directory.is_dir():
        raise ValueError(f"지원자 디렉터리가 없음: {directory}")
    candidates = [load_candidate(p) for p in sorted(directory.glob("*.json"))]
    ids = [c.id for c in candidates]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"지원자 id 중복: {', '.join(dup)}")
    return candidates
```

Run → PASS. 커밋 `feat(scoring): 이력서 모델·줄 번호 렌더링`

---

### Task 3: 결과 모델·가중치·저장

**Files:**
- Create: `src/scoring/result.py`
- Test: `tests/test_result.py`

- [ ] **Step 1: 실패하는 테스트**

```python
from scoring.result import (CandidateScore, MatchResult, PositionScore, PostingRef, RequirementJudgment,
                            Weights, load_result, results_dir, save_result)


def sample() -> MatchResult:
    j = RequirementJudgment(requirement_id="r1", text="고졸 이상", priority="must", category="education",
                            status="met", quotes=["[학력] 고등학교 · 졸업"], reason="고졸", credit=1.0, contribution=70.0)
    ps = PositionScore(position=None, score=70, raw=70.0, must_met=1, must_total=1, preferred_met=0,
                       preferred_total=1, unmet_must=[], unknown=[], judgments=[j])
    cs = CandidateScore(rank=1, candidate_id="c1", name="김", score=70, raw=70.0, position=None,
                        positions=[ps], summary=["필수 1개 중 1개 충족"], excluded_sensitive=[])
    return MatchResult(posting=PostingRef(site="saramin", posting_id="55", title="t", criteria_extracted_at="t0"),
                       matched_at="t1", model="m", weights=Weights(), candidates=[cs])


def test_weights_defaults_match_adr_0017():
    w = Weights()
    assert (w.must_share, w.gate, w.partial, w.unknown) == (0.7, 0.8, 0.5, 0.5)


def test_save_load_roundtrip_atomic(tmp_path):
    path = save_result(tmp_path, sample())
    assert path == results_dir(tmp_path, "saramin", "55") / "ranking.json"
    assert not list(path.parent.glob("*.tmp"))
    assert load_result(tmp_path, "saramin", "55") == sample()
    assert load_result(tmp_path, "saramin", "99") is None
```

- [ ] **Step 2: 구현** — `src/scoring/result.py`

```python
"""매칭 결과 모델과 저장 (스펙 03 6.2). 저장은 원자적으로 — ranking.json이 있으면 완전한 결과다."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .candidate import Status

RESULT_FILE = "ranking.json"


class Weights(BaseModel):
    """점수식 상수 (ADR-0017). 결과 파일에 함께 저장한다."""
    must_share: float = 0.7      # base = must_share·M + (1-must_share)·P
    gate: float = 0.8            # 필수 미충족 1개마다 곱함
    partial: float = 0.5
    unknown: float = 0.5


class RequirementJudgment(BaseModel):
    requirement_id: str
    text: str
    priority: Literal["must", "preferred"]
    category: str
    status: Status
    quotes: list[str] = Field(default_factory=list)
    reason: str = ""
    rule: Optional[Literal["education_level", "experience_years"]] = None
    flags: list[str] = Field(default_factory=list)
    credit: Optional[float] = None
    contribution: float = 0.0


class PositionScore(BaseModel):
    position: Optional[str]
    score: int
    raw: float
    must_met: int
    must_total: int
    preferred_met: int
    preferred_total: int
    unmet_must: list[str]
    unknown: list[str]
    judgments: list[RequirementJudgment]


class CandidateScore(BaseModel):
    rank: int
    candidate_id: str
    name: str
    score: int
    raw: float
    position: Optional[str]
    positions: list[PositionScore]
    summary: list[str]
    excluded_sensitive: list[str]


class PostingRef(BaseModel):
    site: str
    posting_id: str
    title: str
    criteria_extracted_at: str


class MatchResult(BaseModel):
    schema_version: int = 1
    posting: PostingRef
    matched_at: str
    model: str
    weights: Weights
    candidates: list[CandidateScore]


def results_dir(data_dir: Path, site: str, posting_id: str) -> Path:
    return data_dir / "results" / site / posting_id


def save_result(data_dir: Path, result: MatchResult) -> Path:
    directory = results_dir(data_dir, result.posting.site, result.posting.posting_id)
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / RESULT_FILE
    tmp = final.with_suffix(".json.tmp")
    tmp.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, final)
    return final


def load_result(data_dir: Path, site: str, posting_id: str) -> Optional[MatchResult]:
    path = results_dir(data_dir, site, posting_id) / RESULT_FILE
    if not path.exists():
        return None
    return MatchResult.model_validate_json(path.read_text(encoding="utf-8"))
```

Run → PASS. 커밋 `feat(scoring): 결과 모델·가중치·저장`

---

### Task 4: 규칙 — 학력 서열·경력 연수

**Files:**
- Create: `src/scoring/rules.py`
- Test: `tests/test_rules.py`

- [ ] **Step 1: 실패하는 테스트**

```python
import pytest

from scoring.candidate import Candidate
from scoring.rules import education_status, experience_years, years_status


def cand(education=(), experiences=()):
    return Candidate(id="c", name="n", education=list(education), experiences=list(experiences))


def edu(level, status="graduated"):
    return {"level": level, "school": "s", "status": status}


def job(start, end):
    return {"company": "c", "role": "r", "start": start, "end": end}


@pytest.mark.parametrize("education, minimum, expected", [
    ([edu("master")], "bachelor", None),                    # 상위 학력은 충족 → LLM 판정 유지
    ([edu("associate")], "high_school", None),
    ([edu("bachelor", "expected")], "bachelor", None),      # 졸업 예정도 수준은 인정 (기한은 LLM)
    ([edu("high_school")], "bachelor", "unmet"),
    ([edu("high_school"), edu("bachelor", "dropped")], "bachelor", "unmet"),   # 중퇴는 세지 않음
    ([edu("bachelor", "enrolled")], "bachelor", "unmet"),
    ([], "high_school", "unknown"),                         # 학력 정보 없음 ≠ 미달
])
def test_education_status(education, minimum, expected):
    status, reason = education_status(cand(education=education), minimum)
    assert status == expected and "요구" in reason


def test_experience_years_merges_overlaps_and_ongoing():
    c = cand(experiences=[job("2020-01", "2020-12"), job("2020-07", "2021-06"), job("2023-01", None)])
    assert experience_years(c, [1, 2], today="2026-10") == pytest.approx(1.5)          # 2020-01~2021-06
    assert experience_years(c, [3], today="2026-10") == pytest.approx(3 + 10 / 12)     # 2023-01~2026-10
    assert experience_years(c, [1, 99, 0], today="2026-10") == pytest.approx(1.0)      # 없는 번호는 무시


@pytest.mark.parametrize("have, need, expected", [(3, 3, "met"), (1.8, 3, "partial"), (1.7, 3, "unmet"), (0, 0, "met")])
def test_years_status(have, need, expected):
    assert years_status(have, need) == expected
```

- [ ] **Step 2: 구현** — `src/scoring/rules.py`

```python
"""LLM에게 맡기지 않는 계산 (ADR-0015): 학력 서열, 경력 기간 병합."""
from __future__ import annotations

from typing import Optional

from .candidate import LEVEL_LABEL, Candidate, Status

ORDER = ["high_school", "associate", "bachelor", "master", "phd"]
COUNTED = {"graduated", "expected"}     # 졸업 예정은 수준으로 인정 — 기한 조건은 요건 문구로 LLM이 판정
PARTIAL_RATIO = 0.6


def education_status(c: Candidate, minimum: str) -> tuple[Optional[Status], str]:
    """None = 수준 충족(LLM 판정 유지), "unmet" = 미달, "unknown" = 학력 정보 없음."""
    need = f"요구 {LEVEL_LABEL[minimum]} 이상"
    if not c.education:
        return "unknown", f"학력 정보 없음 / {need}"
    levels = [e.level for e in c.education if e.status in COUNTED]
    if not levels:
        return "unmet", f"졸업(예정) 학력 없음 / {need}"
    top = max(levels, key=ORDER.index)
    status = None if ORDER.index(top) >= ORDER.index(minimum) else "unmet"
    return status, f"최고 학력 {LEVEL_LABEL[top]} / {need}"


def _month(ym: str) -> int:
    year, month = ym.split("-")[:2]
    return int(year) * 12 + int(month) - 1


def experience_years(c: Candidate, indices: list[int], *, today: str) -> float:
    """1부터 세는 경력 번호들의 기간을 겹침 병합해 연수로. 시작·끝 달을 모두 포함한다."""
    spans = sorted(
        (_month(x.start), _month(x.end or today) + 1)
        for i, x in enumerate(c.experiences, start=1) if i in set(indices)
    )
    months, cur_start, cur_end = 0, None, None
    for start, end in spans:
        if cur_end is None or start > cur_end:
            months += (cur_end - cur_start) if cur_end is not None else 0
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        months += cur_end - cur_start
    return months / 12


def years_status(have: float, need: float) -> Status:
    ratio = have / need if need > 0 else 1.0
    return "met" if ratio >= 1 else "partial" if ratio >= PARTIAL_RATIO else "unmet"
```

Run → PASS. 커밋 `feat(scoring): 학력 서열·경력 연수 규칙`

---

### Task 5: 집계·기여도·설명

**Files:**
- Create: `src/scoring/score.py`
- Test: `tests/test_score.py`

- [ ] **Step 1: 실패하는 테스트** — 설계 원칙이 깨지면 실패하는 것만

```python
import pytest

from scoring.result import RequirementJudgment, Weights
from scoring.score import aggregate, summarize


def j(rid, status, priority="must", text=None, quotes=()):
    return RequirementJudgment(requirement_id=rid, text=text or rid, priority=priority, category="other",
                               status=status, quotes=list(quotes))


def test_contributions_sum_to_raw_score_and_all_met_is_100():
    ps = aggregate([j("r1", "met"), j("r2", "met"), j("r3", "met", "preferred")], None)
    assert ps.score == 100
    assert sum(x.contribution for x in ps.judgments) == pytest.approx(ps.raw)


def test_must_only_met_without_preferred_strengths_is_70():
    ps = aggregate([j("r1", "met"), j("r2", "unmet", "preferred"), j("r3", "unmet", "preferred")], None)
    assert ps.score == 70


def test_unmet_must_applies_gate_but_unknown_does_not():
    unmet = aggregate([j("r1", "met"), j("r2", "unmet")], None)          # M=0.5, gate 0.8 → 40
    unknown = aggregate([j("r1", "met"), j("r2", "unknown")], None)      # M=0.75, gate 1 → 75
    assert (unmet.score, unknown.score) == (40, 75)
    assert unmet.unmet_must == ["r2"] and unknown.unknown == ["r2"]


def test_not_applicable_is_excluded_from_denominator():
    ps = aggregate([j("r1", "met"), j("r2", "not_applicable")], None)
    assert ps.score == 100 and ps.must_total == 1
    assert ps.judgments[1].credit is None and ps.judgments[1].contribution == 0


def test_no_preferred_means_base_is_must_average():
    assert aggregate([j("r1", "met"), j("r2", "partial")], None).score == 75


def test_custom_weights_rescore_without_llm():
    js = [j("r1", "met"), j("r2", "unmet", "preferred")]
    assert aggregate(js, None, Weights(must_share=0.5)).score == 50


def test_nothing_to_score_is_an_error():
    with pytest.raises(ValueError):
        aggregate([j("r1", "not_applicable")], None)


def test_summary_is_built_from_judgments():
    ps = aggregate([j("r1", "met", text="대졸"), j("r2", "unmet", text="공인영어성적", quotes=["[어학] 없음"]),
                    j("r3", "unknown", text="해외여행 결격사유 없음"), j("r4", "met", "preferred", text="회화")], None)
    lines = summarize(ps, excluded_sensitive=["장애인 우대"])
    assert lines[0] == "필수 3개 중 1개 충족 · 우대 1개 중 1개 충족"
    assert '미충족: [필수] 공인영어성적 (이력서: "[어학] 없음")' in lines
    assert "확인 필요: 해외여행 결격사유 없음" in lines
    assert lines[-1] == "법정 우대 1개는 점수에 반영하지 않음"
```

- [ ] **Step 2: 구현** — `src/scoring/score.py`

```python
"""점수 집계와 설명 — 순수 함수 (ADR-0017). 판정만 있으면 LLM 없이 다시 계산할 수 있다."""
from __future__ import annotations

import math
from typing import Optional

from .result import PositionScore, RequirementJudgment, Weights


def credit(status: str, w: Weights) -> Optional[float]:
    return {"met": 1.0, "partial": w.partial, "unknown": w.unknown, "unmet": 0.0}.get(status)


def aggregate(judgments: list[RequirementJudgment], position: Optional[str],
              weights: Weights = Weights()) -> PositionScore:
    js = [x.model_copy() for x in judgments]
    for x in js:
        x.credit, x.contribution = credit(x.status, weights), 0.0
    must = [x for x in js if x.priority == "must" and x.credit is not None]
    pref = [x for x in js if x.priority == "preferred" and x.credit is not None]
    if not must and not pref:
        raise ValueError("점수를 매길 요건이 없음 (모두 해당 없음)")
    groups = [(must, weights.must_share), (pref, 1 - weights.must_share)] if must and pref else [(must or pref, 1.0)]
    unmet_must = [x.requirement_id for x in must if x.status == "unmet"]
    gate = weights.gate ** len(unmet_must)
    for group, share in groups:
        for x in group:
            x.contribution = 100 * gate * share * x.credit / len(group)
    raw = sum(x.contribution for x in js)
    return PositionScore(
        position=position, score=math.floor(raw + 0.5), raw=raw,
        must_met=sum(x.status == "met" for x in must), must_total=len(must),
        preferred_met=sum(x.status == "met" for x in pref), preferred_total=len(pref),
        unmet_must=unmet_must, unknown=[x.requirement_id for x in js if x.status == "unknown"],
        judgments=js,
    )


def _tag(x: RequirementJudgment) -> str:
    return "필수" if x.priority == "must" else "우대"


def summarize(ps: PositionScore, excluded_sensitive: list[str]) -> list[str]:
    head = f"필수 {ps.must_total}개 중 {ps.must_met}개 충족"
    if ps.preferred_total:
        head += f" · 우대 {ps.preferred_total}개 중 {ps.preferred_met}개 충족"
    lines = [head]
    pick = lambda status: [x for x in ps.judgments if x.status == status]
    if unmet := pick("unmet"):
        lines.append("미충족: " + "; ".join(
            f"[{_tag(x)}] {x.text}" + (f' (이력서: "{x.quotes[0]}")' if x.quotes else "") for x in unmet))
    if partial := pick("partial"):
        lines.append("부분 충족: " + "; ".join(f"[{_tag(x)}] {x.text}" for x in partial))
    if unknown := pick("unknown"):
        lines.append("확인 필요: " + ", ".join(x.text for x in unknown))
    if excluded_sensitive:
        lines.append(f"법정 우대 {len(excluded_sensitive)}개는 점수에 반영하지 않음")
    return lines
```

Run → PASS. 커밋 `feat(scoring): 점수 집계·기여도·템플릿 설명`

---

### Task 6: 판정 프롬프트·LLM 출력 스키마

**Files:**
- Create: `src/scoring/judge.py`
- Test: `tests/test_judge.py`

- [ ] **Step 1: 실패하는 테스트**

```python
from openai.lib._pydantic import to_strict_json_schema

from scoring.candidate import Candidate
from scoring.judge import LLMJudgeOutput, build_prompt, judge

from .fakes import FakeLLM
from .scoring_fixtures import make_criteria, make_requirement

CAND = Candidate(id="c9", name="박", education=[{"level": "high_school", "school": "s"}],
                 meta={"target_posting": "55", "label": "mismatch"})


def test_output_schema_is_openai_strict_compatible():
    assert to_strict_json_schema(LLMJudgeOutput)["additionalProperties"] is False


def test_prompt_lists_requirements_with_scope_and_rendered_resume_only():
    reqs = [make_requirement("r1", "고등학교 졸업 이상"), make_requirement("r2", "화공 전공", positions=["공정"])]
    prompt = build_prompt(make_criteria(reqs), reqs, CAND)
    assert "- r1 [필수 · other · 모집분야: 전체] 고등학교 졸업 이상" in prompt
    assert "- r2 [필수 · other · 모집분야: 공정] 화공 전공" in prompt
    assert "L02 [학력] 고등학교 · s · 졸업" in prompt
    assert "mismatch" not in prompt


def test_judge_calls_structured_once_with_cache_tag():
    reqs = [make_requirement("r1", "고등학교 졸업 이상")]
    llm = FakeLLM(structured=[LLMJudgeOutput(judgments=[])])
    judge(llm, make_criteria(reqs), CAND, reqs, model="m")
    assert llm.calls == [("structured", "judge-55-c9")]
```

공용 픽스처 `tests/scoring_fixtures.py`:

```python
from preprocessing.criteria import (Conditions, CriteriaSource, EvidenceRef, PostingCriteria, Position,
                                    Requirement)


def make_requirement(rid, text, priority="must", category="other", positions=(), sensitive=False,
                     min_education=None, min_years=None):
    return Requirement(id=rid, text=text, normalized=text, priority=priority, category=category,
                       positions=list(positions), min_years=min_years, min_education=min_education,
                       sensitive=sensitive, evidence=EvidenceRef(quote=text, image_index=0, slice_index=0))


def make_criteria(requirements, positions=(), posting_id="55", suitable=True):
    return PostingCriteria(
        source=CriteriaSource(site="saramin", posting_id=posting_id, snapshot_fetched_at="t0", image_sha256=["x"]),
        extracted_at="t1", models={"transcribe": "v", "structure": "t"}, title="테스트 공고", company="OO",
        job_family="테스트 직군", positions=[Position(name=p, group=None, duties=None, location=None) for p in positions],
        requirements=list(requirements), conditions=Conditions(employment_type=None, locations=[], schedule=None, others=[]),
        suitable=suitable, warnings=[],
    )
```

(`PostingCriteria` 필드 이름은 `src/preprocessing/criteria.py`를 따른다 — 다르면 픽스처를 맞춘다.)

- [ ] **Step 2: 구현** — `src/scoring/judge.py`

```python
"""요건별 판정 — LLM이 맡는 유일한 부분 (ADR-0015). 숫자 점수는 내지 않는다."""
from __future__ import annotations

from pydantic import BaseModel

from llm import LLM
from preprocessing.criteria import PostingCriteria, Requirement

from .candidate import Candidate, Status, render

JUDGE_SYSTEM = """당신은 채용 서류 심사자다. 공고의 요건 목록과 지원자 이력서(줄 번호가 붙은 텍스트)를 받아, 요건마다 이력서가 그 요건을 충족하는지 판정한다.

판정 상태:
- met: 이력서에 요건을 충족한다는 사실이 있다.
- partial: 일부만 충족한다 (기간·수준 부족, 인접 분야, 기술·키워드를 나열만 하고 경력·학력·자격으로 뒷받침하지 않음).
- unmet: 이력서가 요건과 반대되는 사실을 말한다 (다른 전공, 불가하다고 밝힘, 기한을 넘김 등).
- unknown: 이력서에 판단할 정보가 없다. 정보가 없다는 이유로 unmet을 주지 않는다.
- not_applicable: 요건에 대상 조건("~의 경우")이 있고 지원자가 그 대상이 아니다.

규칙:
1. 이력서에 쓰인 사실만으로 판단한다. 추측하지 않는다.
2. 같은 뜻의 다른 표현, 상위·하위 개념을 인정한다 (학과·자격·직무·지명이 달라도 같은 계열·같은 지역이면 충족).
3. 학력 요건은 그 수준 이상이면 충족이다. 요건 문구 안의 기한·단서(졸업 예정 시점, 유효 기간 등)도 판정에 포함한다.
4. [기술] 줄에만 있는 내용은 partial을 넘지 않는다.
5. met·partial·unmet에는 근거 인용(quotes)을 1개 이상 넣는다. 인용은 이력서 한 줄의 내용을 그대로 옮기되 줄 번호(L01 등)는 빼고, 여러 줄을 이어 붙이지 않는다.
6. reason은 한국어 한 문장.
7. experience 유형 요건이면 관련 있는 경력 번호([경력 N]의 N)를 relevant_experience에 넣는다. 다른 유형이면 빈 목록.
8. 요건마다 정확히 하나의 판정을 낸다. requirement_id는 주어진 id를 그대로 쓴다.
"""


class LLMJudgment(BaseModel):
    requirement_id: str
    status: Status
    quotes: list[str]
    reason: str
    relevant_experience: list[int]


class LLMJudgeOutput(BaseModel):
    judgments: list[LLMJudgment]


def requirement_line(r: Requirement) -> str:
    scope = ", ".join(r.positions) if r.positions else "전체"
    tag = "필수" if r.priority == "must" else "우대"
    return f"- {r.id} [{tag} · {r.category} · 모집분야: {scope}] {r.text}"


def build_prompt(criteria: PostingCriteria, requirements: list[Requirement], candidate: Candidate) -> str:
    company = f" ({criteria.company})" if criteria.company else ""
    return "\n".join([
        f"# 공고: {criteria.title}{company}", f"직군: {criteria.job_family}", "",
        "# 요건", *[requirement_line(r) for r in requirements], "",
        "# 이력서", render(candidate),
    ])


def judge(llm: LLM, criteria: PostingCriteria, candidate: Candidate, requirements: list[Requirement],
          *, model: str) -> LLMJudgeOutput:
    return llm.structured(model=model, system=JUDGE_SYSTEM, user=build_prompt(criteria, requirements, candidate),
                          schema=LLMJudgeOutput, tag=f"judge-{criteria.source.posting_id}-{candidate.id}")
```

Run → PASS. 커밋 `feat(scoring): 판정 프롬프트·출력 스키마`

---

### Task 7: 판정 검증·규칙 보정

**Files:**
- Create: `src/scoring/verify.py`
- Test: `tests/test_scoring_verify.py`

- [ ] **Step 1: 실패하는 테스트**

```python
from scoring.candidate import Candidate, render
from scoring.judge import LLMJudgeOutput, LLMJudgment
from scoring.verify import judge_requirements

from .scoring_fixtures import make_requirement

CAND = Candidate(id="c", name="n", education=[{"level": "high_school", "school": "청주고"}],
                 experiences=[{"company": "A식품", "role": "포장", "start": "2022-01", "end": "2023-12"}],
                 declarations=["야간근무 가능"])


def out(*items):
    return LLMJudgeOutput(judgments=[LLMJudgment(requirement_id=i, status=s, quotes=list(q), reason="r",
                                                 relevant_experience=list(e)) for i, s, q, e in items])


def run(reqs, *items):
    return {x.requirement_id: x for x in judge_requirements(out(*items), reqs, CAND, today="2026-10")}


def test_quote_must_exist_in_rendered_resume_else_unknown():
    reqs = [make_requirement("r1", "야간근무"), make_requirement("r2", "운전면허")]
    got = run(reqs, ("r1", "met", ["L05 [자기 신고] 야간근무 가능"], []),   # 줄 번호가 붙어도 인정
              ("r2", "met", ["[자격증] 1종 보통"], []))                       # 이력서에 없음
    assert (got["r1"].status, got["r1"].flags) == ("met", [])
    assert (got["r2"].status, got["r2"].flags) == ("unknown", ["quote_not_found"])


def test_judgment_without_evidence_and_missing_or_unknown_ids():
    reqs = [make_requirement("r1", "a"), make_requirement("r2", "b")]
    got = run(reqs, ("r1", "unmet", [], []), ("r9", "met", [], []), ("r1", "met", [], []))
    assert (got["r1"].status, got["r1"].flags) == ("unknown", ["no_evidence"])
    assert (got["r2"].status, got["r2"].flags) == ("unknown", ["not_judged"])
    assert set(got) == {"r1", "r2"}


def test_education_rule_overrides_llm_when_below_minimum():
    reqs = [make_requirement("r1", "대졸", category="education", min_education="bachelor"),
            make_requirement("r2", "고졸", category="education", min_education="high_school")]
    got = run(reqs, ("r1", "met", ["[학력] 고등학교 · 청주고 · 졸업"], []),
              ("r2", "partial", ["[학력] 고등학교 · 청주고 · 졸업"], []))
    assert (got["r1"].status, got["r1"].rule) == ("unmet", "education_level")
    assert (got["r2"].status, got["r2"].rule) == ("partial", None)          # 수준 충족 → LLM 판정 유지


def test_experience_rule_computes_years_from_selected_jobs():
    reqs = [make_requirement("r1", "생산 경력 3년", category="experience", min_years=3)]
    got = run(reqs, ("r1", "met", ["[경력 1] A식품 · 포장 · 2022-01~2023-12"], [1]))
    assert (got["r1"].status, got["r1"].rule) == ("partial", "experience_years")
    assert "2.0년" in got["r1"].reason and "3년" in got["r1"].reason
```

- [ ] **Step 2: 구현** — `src/scoring/verify.py`

```python
"""판정 검증과 규칙 보정 — 코드가 책임지는 부분 (ADR-0015).

1. 인용이 렌더링된 이력서에 있는지 확인 (없으면 unknown — 환각 방어)
2. 근거 없는 판정, 판정 누락, 모르는 id·중복 보정
3. 학력 서열·경력 연수는 규칙으로 (규칙이 LLM보다 우선)
"""
from __future__ import annotations

import re

from preprocessing.criteria import Requirement
from preprocessing.verify import find_fragments, find_quote

from .candidate import Candidate, render
from .judge import LLMJudgeOutput, LLMJudgment
from .result import RequirementJudgment
from .rules import education_status, experience_years, years_status

LINE_NO = re.compile(r"^\s*L\d+\s*")
NEEDS_EVIDENCE = {"met", "partial", "unmet"}


def _found(quote: str, text: str) -> bool:
    return find_quote(quote, text) is not None or find_fragments(quote, text) is not None


def judge_requirements(out: LLMJudgeOutput, requirements: list[Requirement], candidate: Candidate,
                       *, today: str) -> list[RequirementJudgment]:
    text = render(candidate)
    by_id: dict[str, LLMJudgment] = {}
    for j in out.judgments:
        by_id.setdefault(j.requirement_id, j)          # 중복이면 첫 판정
    result = []
    for r in requirements:
        j = by_id.get(r.id)
        if j is None:
            status, quotes, reason, flags, picked = "unknown", [], "판정 누락", ["not_judged"], []
        else:
            quotes = [LINE_NO.sub("", q).strip() for q in j.quotes if q.strip()]
            status, reason, flags, picked = j.status, j.reason, [], j.relevant_experience
            if not all(_found(q, text) for q in quotes):
                status, flags = "unknown", ["quote_not_found"]
            elif status in NEEDS_EVIDENCE and not quotes:
                status, flags = "unknown", ["no_evidence"]
        rule = None
        if r.min_education not in (None, "none"):
            edu, why = education_status(candidate, r.min_education)
            if edu is not None:
                status, reason, rule = edu, why, "education_level"
        if rule is None and r.category == "experience" and r.min_years:
            have = experience_years(candidate, picked, today=today)
            status, rule = years_status(have, r.min_years), "experience_years"
            reason = f"관련 경력 {have:.1f}년 / 요구 {r.min_years:g}년"
        result.append(RequirementJudgment(
            requirement_id=r.id, text=r.text, priority=r.priority, category=r.category,
            status=status, quotes=quotes, reason=reason, rule=rule, flags=flags,
        ))
    return result
```

주의: 학력 규칙이 `unknown`을 돌려주면(학력 정보 없음) 그것도 규칙 결과로 쓴다. 규칙이 `None`(수준 충족)이면 LLM 판정을 그대로 둔다.

Run → PASS. 커밋 `feat(scoring): 판정 인용 검증·규칙 보정`

---

### Task 8: 스코어링 서비스

**Files:**
- Create: `src/scoring/service.py`
- Test: `tests/test_scoring_service.py`

- [ ] **Step 1: 실패하는 테스트**

```python
import json

import pytest

from preprocessing.criteria import criteria_dir, save_criteria
from scoring.judge import LLMJudgeOutput, LLMJudgment
from scoring.result import load_result
from scoring.service import applicable, match, target_positions
from settings import Settings

from .fakes import FakeLLM
from .scoring_fixtures import make_criteria, make_requirement


def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", judge_model="j")


def write_criteria(tmp_path, criteria):
    save_criteria(criteria_dir(tmp_path / "data", "saramin", criteria.source.posting_id), criteria)


def write_candidates(tmp_path, *cands):
    d = tmp_path / "cands"
    d.mkdir(exist_ok=True)
    for c in cands:
        (d / f"{c['id']}.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    return d


def person(cid, declarations=(), desired=(), label="perfect"):
    return {"id": cid, "name": cid, "declarations": list(declarations), "desired_positions": list(desired),
            "meta": {"target_posting": "55", "label": label}}


def by_declaration(user: str) -> LLMJudgeOutput:
    """이력서의 [자기 신고] 줄에 요건 문구가 있으면 met, '불가'가 있으면 unmet, 없으면 unknown — 결정적 대역."""
    lines = [l.split(" ", 1)[1] for l in user.split("# 이력서", 1)[1].strip().splitlines()]
    req_lines = [l for l in user.split("# 이력서")[0].splitlines() if l.startswith("- r")]
    out = []
    for rl in req_lines:
        rid, text = rl[2:].split(" ", 1)[0], rl.rsplit("] ", 1)[1]
        hit = next((l for l in lines if l.startswith("[자기 신고]") and text in l), None)
        status = "unknown" if hit is None else ("unmet" if "불가" in hit else "met")
        out.append(LLMJudgment(requirement_id=rid, status=status, quotes=[hit] if hit else [], reason="r",
                               relevant_experience=[]))
    return LLMJudgeOutput(judgments=out)


REQS = [make_requirement("r1", "야간근무"), make_requirement("r2", "인근거주", priority="preferred"),
        make_requirement("r3", "보훈", priority="preferred", sensitive=True)]


def test_ranks_by_score_and_saves(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]), person("b", ["야간근무 가능", "인근거주"]),
                         person("c", ["야간근무 불가"], label="mismatch"))
    llm = FakeLLM(structured=[by_declaration] * 3)
    result = match("55", settings(tmp_path), llm=llm, candidates_dir=d, log=lambda m: None)
    assert [(c.candidate_id, c.score, c.rank) for c in result.candidates] == [("b", 100, 1), ("a", 85, 2), ("c", 12, 3)]
    # a: 야간 met, 인근 unknown(0.5) → 70+15 / c: 야간 unmet → (0 + 0.3·0.5)·0.8
    assert load_result(tmp_path / "data", "saramin", "55") == result


def test_sensitive_requirements_are_not_sent_or_scored(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]))
    seen = []
    llm = FakeLLM(structured=[lambda user: (seen.append(user), by_declaration(user))[1]])
    result = match("55", settings(tmp_path), llm=llm, candidates_dir=d, log=lambda m: None)
    assert "보훈" not in seen[0]
    assert result.candidates[0].excluded_sensitive == ["보훈"]
    assert {x.requirement_id for x in result.candidates[0].positions[0].judgments} == {"r1", "r2"}


def test_meta_label_does_not_change_scores(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    scores = []
    for label in ("perfect", "mismatch"):
        d = write_candidates(tmp_path, person("a", ["야간근무 가능"], label=label))
        r = match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration]), candidates_dir=d,
                  refresh=True, log=lambda m: None)
        scores.append(r.candidates[0].raw)
    assert scores[0] == scores[1]


def test_positions_desired_then_best(tmp_path):
    reqs = [make_requirement("r1", "야간근무"), make_requirement("r2", "화공", positions=["공정"]),
            make_requirement("r3", "기계", positions=["설비"])]
    crit = make_criteria(reqs, positions=["공정", "설비", "재무"])
    desired = person("a", ["야간근무 가능", "기계"], desired=["설비", "없는분야"])
    assert target_positions(crit, _cand(desired)) == ["설비"]
    assert target_positions(crit, _cand(person("b"))) == ["공정", "설비", "재무"]
    assert [r.id for r in applicable(crit, "공정")] == ["r1", "r2"]
    write_criteria(tmp_path, crit)
    d = write_candidates(tmp_path, person("b", ["야간근무 가능", "기계"]))
    result = match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration]), candidates_dir=d,
                   log=lambda m: None)
    top = result.candidates[0]
    # 공정: r1 met·r2 unknown → 75 / 설비: r1·r3 met → 100 / 재무: r1 met → 100 — 동점이면 먼저 평가한 분야
    assert (top.position, top.score) == ("설비", 100)
    assert len(top.positions) == 3


def _cand(data):
    from scoring.candidate import Candidate
    return Candidate.model_validate(data)


def test_reuses_saved_result_without_llm_unless_refresh(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]))
    match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration]), candidates_dir=d, log=lambda m: None)
    llm = FakeLLM()
    match("55", settings(tmp_path), llm=llm, candidates_dir=d, log=lambda m: None)
    assert llm.calls == []


def test_missing_or_unsuitable_criteria(tmp_path):
    d = write_candidates(tmp_path, person("a"))
    with pytest.raises(RuntimeError, match="jobfit extract 55"):
        match("55", settings(tmp_path), llm=FakeLLM(), candidates_dir=d, log=lambda m: None)
    write_criteria(tmp_path, make_criteria([make_requirement("r1", "보훈", sensitive=True)]))
    with pytest.raises(RuntimeError, match="평가할 요건"):
        match("55", settings(tmp_path), llm=FakeLLM(), candidates_dir=d, log=lambda m: None)


def test_unseen_job_family_with_years_rule(tmp_path):
    """코드에 없는 직군(바리스타)도 요건 데이터만으로 점수가 나온다 — 일반화 스모크."""
    reqs = [make_requirement("r1", "바리스타 경력 2년 이상", category="experience", min_years=2)]
    write_criteria(tmp_path, make_criteria(reqs, posting_id="77"))
    d = write_candidates(tmp_path, {"id": "x", "name": "x", "experiences": [
        {"company": "카페", "role": "바리스타", "start": "2025-01", "end": "2025-12"}]})
    out = LLMJudgeOutput(judgments=[LLMJudgment(requirement_id="r1", status="met",
                                                quotes=["[경력 1] 카페 · 바리스타 · 2025-01~2025-12"], reason="r",
                                                relevant_experience=[1])])
    result = match("77", settings(tmp_path), llm=FakeLLM(structured=[out]), candidates_dir=d, log=lambda m: None)
    j = result.candidates[0].positions[0].judgments[0]
    assert (j.status, j.rule, result.candidates[0].score) == ("unmet", "experience_years", 0)   # 1년/2년 = 0.5 < 0.6
```

- [ ] **Step 2: 구현** — `src/scoring/service.py`

```python
"""스코어링 오케스트레이션. CLI·API가 같은 함수를 호출한다 (ADR-0002).

입력은 criteria.json과 이력서 JSON뿐 — 공고 이미지·HTML은 읽지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from crawler.saramin import parse_rec_idx
from crawler.service import SITE
from llm import LLM
from preprocessing.criteria import PostingCriteria, Requirement, criteria_dir, load_criteria
from settings import Settings

from .candidate import Candidate, load_candidates
from .judge import judge
from .result import CandidateScore, MatchResult, PostingRef, Weights, load_result, save_result
from .score import aggregate, summarize
from .verify import judge_requirements


def target_positions(criteria: PostingCriteria, candidate: Candidate) -> list[Optional[str]]:
    names = [p.name for p in criteria.positions]
    if len(names) <= 1:
        return [None]
    chosen = [p for p in candidate.desired_positions if p in names]
    return chosen or names


def applicable(criteria: PostingCriteria, position: Optional[str]) -> list[Requirement]:
    return [r for r in criteria.requirements
            if not r.sensitive and (position is None or not r.positions or position in r.positions)]


def score_candidate(llm: LLM, criteria: PostingCriteria, candidate: Candidate, *, model: str, today: str,
                    weights: Weights) -> CandidateScore:
    positions = target_positions(criteria, candidate)
    union: dict[str, Requirement] = {}
    for p in positions:
        for r in applicable(criteria, p):
            union.setdefault(r.id, r)
    reqs = list(union.values())
    out = judge(llm, criteria, candidate, reqs, model=model)
    judged = {j.requirement_id: j for j in judge_requirements(out, reqs, candidate, today=today)}
    per_position = [aggregate([judged[r.id] for r in applicable(criteria, p)], p, weights) for p in positions]
    best = max(per_position, key=lambda ps: ps.raw)
    excluded = [r.text for r in criteria.requirements if r.sensitive]
    return CandidateScore(rank=0, candidate_id=candidate.id, name=candidate.name, score=best.score, raw=best.raw,
                          position=best.position, positions=per_position, summary=summarize(best, excluded),
                          excluded_sensitive=excluded)


def match(ref: str, settings: Settings, *, llm: LLM, candidates_dir: Path, refresh: bool = False,
          log: Callable[[str], None] = print, weights: Weights = Weights()) -> MatchResult:
    posting_id = parse_rec_idx(ref)
    if not refresh and (existing := load_result(settings.data_dir, SITE, posting_id)) is not None:
        log(f"공고 {posting_id}: 기존 매칭 결과 사용 (--refresh로 다시)")
        return existing
    criteria = load_criteria(criteria_dir(settings.data_dir, SITE, posting_id))
    if criteria is None:
        raise RuntimeError(f"공고 {posting_id}의 조건이 없음 — 먼저 `jobfit extract {posting_id}`")
    if not criteria.suitable or not applicable(criteria, None):
        raise RuntimeError(f"공고 {posting_id}는 평가할 요건이 없음 (suitable={criteria.suitable})")
    candidates = load_candidates(candidates_dir)
    matched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    scores = []
    for c in candidates:
        log(f"공고 {posting_id}: {c.id} 판정")
        scores.append(score_candidate(llm, criteria, c, model=settings.judge_model, today=matched_at[:7],
                                      weights=weights))
    scores.sort(key=lambda s: (-s.raw, s.candidate_id))
    for i, s in enumerate(scores, start=1):
        s.rank = i
    result = MatchResult(
        posting=PostingRef(site=SITE, posting_id=posting_id, title=criteria.title,
                           criteria_extracted_at=criteria.extracted_at),
        matched_at=matched_at, model=settings.judge_model, weights=weights, candidates=scores,
    )
    save_result(settings.data_dir, result)
    return result
```

`by_declaration` 대역은 `[자기 신고]` 줄에서 요건 문구를 찾는 단순한 결정적 판정기다 — 그래서 `test_positions_desired_then_best`의 "기계"도 자기 신고에 넣는다.

Run: `pytest -q` → PASS. 커밋 `feat(scoring): 매칭 서비스 — 분야별 점수·랭킹·저장`

---

### Task 9: 목업 이력서 12건과 데이터셋 평가 도구

**Files:**
- Create: `dataset/candidates/*.json` (12건), `dataset/README.md`, `src/scoring/evaluate.py`
- Test: `tests/test_dataset.py`, `tests/test_scoring_evaluate.py`

- [ ] **Step 1: 데이터셋 구성 테스트 (먼저 실패)**

```python
from collections import Counter

from scoring.candidate import load_candidates
from settings import ROOT

DATASET = ROOT / "dataset" / "candidates"


def test_twelve_candidates_two_postings_with_2_3_1_split():
    cands = load_candidates(DATASET)
    assert len(cands) == 12
    by_posting = Counter((c.meta.target_posting, c.meta.label) for c in cands)
    for posting in ("55189170", "55162188"):
        assert (by_posting[(posting, "perfect")], by_posting[(posting, "partial")],
                by_posting[(posting, "mismatch")]) == (2, 3, 1)


def test_every_candidate_documents_intent_and_expected_judgments():
    for c in load_candidates(DATASET):
        assert c.meta.intent and c.meta.expected, c.id
        assert c.id.split("-")[1] == c.meta.label, c.id


def test_no_sensitive_personal_fields():
    for path in DATASET.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        for word in ("장애", "보훈", "생년", "나이"):
            assert word not in text, (path.name, word)
```

- [ ] **Step 2: 이력서 작성** — 스펙 03 7장 표대로. 공통 원칙:
  - 사실은 한 필드에 한 번만 (렌더링 한 줄 = 사실 하나).
  - 같은 라벨의 두 사람은 **다른 표현**을 쓴다 (perfect-2는 공고 단어를 피한다).
  - `meta.expected`에는 의도적으로 갈리는 요건만 적는다 (요건 문구의 일부를 `requirement`에).

| 파일 | 핵심 사실 | `meta.expected` |
|---|---|---|
| `soil-perfect-1.json` | 희망 재무 · 경영학 학사 졸업(2026-02) · TOEIC 915(2025-08) · OPIc AL · 군필 · 자기 신고 "2027년 1월 입사 가능", "해외여행 결격사유 없음" | 공인영어 met, 상경계열 met, 영어 회화 met |
| `soil-perfect-2.json` | 희망 공정 · 화학생명공학 석사 졸업 예정(2027-02) · OPIc IH · 병역 "해당 없음" · 화공기사 · 국제학회 영어 발표 · 같은 자기 신고 | 화공 met, 병역 not_applicable, 자격증 met |
| `soil-partial-1.json` | 희망 설비기술 · 기계공학 학사 졸업 · 일반기계기사 · 군필 · 어학 없음, 자기 신고 "공인영어성적 미보유 (2026년 11월 응시 예정)" | 공인영어 unmet, 기계 met |
| `soil-partial-2.json` | 희망 영업/마케팅 · 국제통상학 학사 **졸업 예정(2027-08)** · TOEIC 880 · 회화 능통(어학연수) · 군필 | 대학(원) 기졸업 unmet, 상경계열 met |
| `soil-partial-3.json` | 희망 설비기술·안전환경 · **산업공학** 학사 졸업 · 산업안전기사 · TOEIC 800 · 군필 | 기계/재료 unmet, 화공/안전/환경 unmet, 자격증 met |
| `soil-mismatch-1.json` | 희망 공정 · 고졸 · 화학공장 생산직 10년 · 어학 없음 · skills ["화공", "TOEIC", "영어 회화", "공정관리"] | 대학(원) unmet, 공인영어 unmet, 영어 회화 partial |
| `orion-perfect-1.json` | 고졸 · 청주시 흥덕구 · 식품공장 포장 3년 · 자기 신고 "야간근무 가능" | 야간근무 met, 인근거주 met, 근무경험 met |
| `orion-perfect-2.json` | 전문학사 식품공학 졸업 · 청주시 청원구 오창읍 · 제과 라인 오퍼레이터 2년 · 자기 신고 "3조 2교대 근무 가능" | 고등학교 met, 야간근무 met, 인근거주 met |
| `orion-partial-1.json` | 고졸 · 서울 관악구 · 카페 아르바이트 2년 · 자기 신고 "야간근무 가능" | 인근거주 unmet, 근무경험 unmet |
| `orion-partial-2.json` | 고졸 · 청주 · 식품 포장 4년 · 자기 신고 "야간근무 불가 (육아)" | 야간근무 unmet |
| `orion-partial-3.json` | 고졸 · 세종시 · 물류센터 피킹 1년 · 야간 언급 없음 | 야간근무 unknown, 근무경험 partial |
| `orion-mismatch-1.json` | 컴퓨터공학 석사 · 서울 · 백엔드 개발 5년 · 자기 신고 "야간근무 불가" · skills ["포장", "배합", "청주"] | 야간근무 unmet, 근무경험 partial |

`dataset/README.md`: 위 표(설계 의도), 필드 설명, "`meta`는 평가 전용 — 스코어링은 읽지 않음".

Run: `pytest tests/test_dataset.py -q` → PASS

- [ ] **Step 3: 평가 도구 테스트 (먼저 실패)** — `tests/test_scoring_evaluate.py`

```python
from scoring.candidate import Candidate
from scoring.evaluate import evaluate_ranking
from scoring.result import (CandidateScore, MatchResult, PositionScore, PostingRef, RequirementJudgment,
                            Weights)


def scored(cid, score, judgments=()):
    js = [RequirementJudgment(requirement_id=f"r{i}", text=t, priority="must", category="other", status=s)
          for i, (t, s) in enumerate(judgments, start=1)]
    ps = PositionScore(position=None, score=score, raw=score, must_met=0, must_total=1, preferred_met=0,
                       preferred_total=0, unmet_must=[], unknown=[], judgments=js)
    return CandidateScore(rank=0, candidate_id=cid, name=cid, score=score, raw=score, position=None,
                          positions=[ps], summary=[], excluded_sensitive=[])


def cand(cid, label, posting="55", expected=()):
    return Candidate(id=cid, name=cid, meta={"target_posting": posting, "label": label,
                                             "expected": [{"requirement": r, "status": s} for r, s in expected]})


def result(*scores):
    return MatchResult(posting=PostingRef(site="saramin", posting_id="55", title="t", criteria_extracted_at="t"),
                       matched_at="t", model="m", weights=Weights(), candidates=list(scores))


def test_order_ranges_and_expected_agreement():
    r = result(scored("p", 90, [("공인영어성적 보유", "met")]), scored("q", 60), scored("m", 20),
               scored("other", 95))
    cands = [cand("p", "perfect", expected=[("공인영어성적", "met")]), cand("q", "partial"),
             cand("m", "mismatch", expected=[("야간근무", "unmet")]), cand("other", "perfect", posting="99")]
    ev = evaluate_ranking(r, cands)
    assert ev.order_ok and ev.out_of_range == []
    assert (ev.agreed, ev.expected_total) == (1, 2)
    assert ev.disagreements == ["m: '야간근무' — 해당 요건 없음"]


def test_order_violation_and_range_reported():
    ev = evaluate_ranking(result(scored("p", 70), scored("q", 75), scored("m", 45)),
                          [cand("p", "perfect"), cand("q", "partial"), cand("m", "mismatch")])
    assert not ev.order_ok
    assert ev.out_of_range == ["p 70 (perfect ≥ 85)", "m 45 (mismatch < 40)"]
```

- [ ] **Step 4: 구현** — `src/scoring/evaluate.py`

```python
"""매칭 결과를 목업의 의도(meta)와 비교한다 — 평가 전용. 스코어링 경로는 이 모듈을 쓰지 않는다."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .candidate import Candidate
from .result import MatchResult

RANGES = {"perfect": (85, 101), "partial": (40, 85), "mismatch": (-1, 40)}
RANGE_TEXT = {"perfect": "≥ 85", "partial": "40–84", "mismatch": "< 40"}


@dataclass
class RankingEvaluation:
    order_ok: bool
    out_of_range: list[str] = field(default_factory=list)
    agreed: int = 0
    expected_total: int = 0
    disagreements: list[str] = field(default_factory=list)


def _compact(s: str) -> str:
    return re.sub(r"\s+", "", s)


def evaluate_ranking(result: MatchResult, candidates: list[Candidate]) -> RankingEvaluation:
    posting = result.posting.posting_id
    meta = {c.id: c.meta for c in candidates if c.meta and c.meta.target_posting == posting}
    scored = [s for s in result.candidates if s.candidate_id in meta]
    by_label = {lb: [s.score for s in scored if meta[s.candidate_id].label == lb] for lb in RANGES}
    order_ok = all(
        min(by_label[hi]) > max(by_label[lo])
        for hi, lo in (("perfect", "partial"), ("partial", "mismatch"), ("perfect", "mismatch"))
        if by_label[hi] and by_label[lo]
    )
    ev = RankingEvaluation(order_ok=order_ok)
    for s in scored:
        label = meta[s.candidate_id].label
        lo, hi = RANGES[label]
        if not lo <= s.score < hi:
            ev.out_of_range.append(f"{s.candidate_id} {s.score} ({label} {RANGE_TEXT[label]})")
        best = next(p for p in s.positions if p.position == s.position)
        for e in meta[s.candidate_id].expected:
            ev.expected_total += 1
            hit = next((j for j in best.judgments if _compact(e.requirement) in _compact(j.text)), None)
            if hit is None:
                ev.disagreements.append(f"{s.candidate_id}: '{e.requirement}' — 해당 요건 없음")
            elif hit.status == e.status:
                ev.agreed += 1
            else:
                ev.disagreements.append(f"{s.candidate_id}: '{e.requirement}' 의도 {e.status} / 판정 {hit.status}")
    return ev
```

`out_of_range`는 결과 파일의 지원자 순서(순위 순)를 따른다.

Run → PASS. 커밋 `feat(dataset): 목업 이력서 12건과 의도 대비 평가 도구`

---

### Task 10: CLI — match / result

**Files:**
- Modify: `src/cli.py`, `README.md` (사용법)
- Test: `tests/test_cli.py`

- [ ] **Step 1: 실패하는 테스트** — 어댑터가 서비스를 올바르게 호출하고 결과를 그리는지만

```python
def test_match_prints_ranking_with_intent_labels(monkeypatch, tmp_path):
    from scoring import service as scoring_service
    calls = []

    def fake_match(ref, settings, *, llm, candidates_dir, refresh, log):
        calls.append((ref, candidates_dir, refresh))
        return SAMPLE_RESULT          # tests/test_result.py의 sample()과 같은 모양, candidate_id "c1"

    monkeypatch.setattr(scoring_service, "match", fake_match)
    d = tmp_path / "cands"; d.mkdir()
    (d / "c1.json").write_text('{"id": "c1", "name": "김", "meta": {"target_posting": "55", "label": "perfect"}}',
                               encoding="utf-8")
    res = runner.invoke(app, ["match", "55", "--candidates", str(d)])
    assert res.exit_code == 0, res.output
    assert calls == [("55", d, False)]
    assert "c1" in res.output and "70" in res.output and "perfect" in res.output


def test_result_shows_requirement_evidence(monkeypatch, tmp_path):
    ...  # load_result를 SAMPLE_RESULT로 대체 → `jobfit result 55 --candidate c1` 출력에 "고졸 이상", "충족", "[학력] 고등학교" 포함
    ...  # 없는 결과면 exit 1, "먼저 `jobfit match 55`"
```

- [ ] **Step 2: 구현** — `src/cli.py`에 추가

```python
from scoring import service as scoring_service
from scoring.candidate import load_candidates
from scoring.evaluate import evaluate_ranking
from scoring.result import load_result

CANDIDATES_DIR = ROOT / "dataset" / "candidates"
STATUS_TEXT = {"met": "[green]충족[/green]", "partial": "[yellow]부분[/yellow]", "unmet": "[red]미충족[/red]",
               "unknown": "[cyan]확인 필요[/cyan]", "not_applicable": "[dim]해당 없음[/dim]"}


def _print_ranking(result, candidates) -> None:
    labels = {c.id: (c.meta.label if c.meta and c.meta.target_posting == result.posting.posting_id
                     else "(타 공고)") for c in candidates}
    table = Table("순위", "점수", "지원자", "분야", "필수", "확인 필요", "의도", title=result.posting.title)
    for s in result.candidates:
        best = next(p for p in s.positions if p.position == s.position)
        table.add_row(str(s.rank), str(s.score), f"{s.candidate_id} {s.name}", s.position or "—",
                      f"{best.must_met}/{best.must_total}", str(len(best.unknown)), labels.get(s.candidate_id, ""))
    console.print(table)
    ev = evaluate_ranking(result, candidates)
    if ev.expected_total:
        console.print(f"의도 순서 {'✓' if ev.order_ok else '✗'} · 구간 이탈 {len(ev.out_of_range)} · "
                      f"의도 판정 일치 {ev.agreed}/{ev.expected_total}")
        for line in ev.out_of_range + ev.disagreements:
            console.print(f"  [yellow]{line}[/yellow]")


@app.command("match")
def match_cmd(
    refs: List[str] = typer.Argument(..., help="사람인 공고 URL 또는 rec_idx (여러 개 가능)"),
    candidates: Path = typer.Option(CANDIDATES_DIR, "--candidates", help="이력서 JSON 디렉터리"),
    refresh: bool = typer.Option(False, "--refresh", help="기존 결과를 무시하고 다시 (판정은 캐시 사용)"),
):
    """지원자를 공고 조건으로 판정·점수화하고 랭킹을 data/results/에 저장."""
    settings = load_settings()
    llm = make_llm(settings)
    people = load_candidates(candidates)
    for ref in refs:
        result = scoring_service.match(ref, settings, llm=llm, candidates_dir=candidates, refresh=refresh, log=_log)
        _print_ranking(result, people)


@app.command()
def result(
    ref: str = typer.Argument(..., help="rec_idx 또는 URL"),
    candidate: Optional[str] = typer.Option(None, "--candidate", help="지원자 id — 요건별 근거 표시"),
    candidates: Path = typer.Option(CANDIDATES_DIR, "--candidates"),
):
    """저장된 매칭 결과. --candidate로 요건별 판정·근거·기여 점수."""
    settings = load_settings()
    posting_id = parse_rec_idx(ref)
    res = load_result(settings.data_dir, "saramin", posting_id)
    if res is None:
        console.print(f"[red]결과 없음 — 먼저 `jobfit match {posting_id}`[/red]")
        raise typer.Exit(1)
    if candidate is None:
        _print_ranking(res, load_candidates(candidates))
        return
    s = next((x for x in res.candidates if x.candidate_id == candidate), None)
    if s is None:
        console.print(f"[red]지원자 {candidate} 없음[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{s.rank}위 {s.candidate_id} {s.name} — {s.score}점[/bold]  분야: {s.position or '—'}")
    if len(s.positions) > 1:
        console.print("분야별: " + ", ".join(f"{p.position} {p.score}" for p in s.positions))
    best = next(p for p in s.positions if p.position == s.position)
    table = Table("요건", "구분", "판정", "근거 (이력서)", "사유", "기여")
    for j in best.judgments:
        flag = f" [red]⚑ {', '.join(j.flags)}[/red]" if j.flags else ""
        rule = f" [dim]({j.rule})[/dim]" if j.rule else ""
        table.add_row(j.text, "필수" if j.priority == "must" else "우대", STATUS_TEXT[j.status] + rule + flag,
                      "\n".join(j.quotes) or "—", j.reason, f"{j.contribution:.1f}")
    console.print(table)
    for line in s.summary:
        console.print(f"· {line}")
    if s.excluded_sensitive:
        console.print("[dim]법정 우대 — 점수 미반영 (관계 법령·증빙에 따라 전형에서 별도 적용): "
                      + ", ".join(s.excluded_sensitive) + "[/dim]")
```

README 사용법에 `match`, `result` 추가, 결과 위치 `data/results/` 추가.

Run: `pytest -q` → PASS. 커밋 `feat(cli): match·result 명령`

---

### Task 11: 실제 실행·실험 [수동 — OPENAI_API_KEY 필요]

- [ ] **Step 1: 첫 실행 (교차 평가 포함)**

```bash
uv pip install -e ".[dev]"
jobfit match 55189170 55162188
jobfit result 55189170 --candidate soil-partial-1
jobfit result 55162188 --candidate orion-partial-3
```
확인: 의도 순서 ✓, 구간 이탈, 의도 판정 일치, `quote_not_found`·`no_evidence` 플래그.

- [ ] **Step 2: 실험 Y1 — 판정 모델**

```bash
JOBFIT_JUDGE_MODEL=gpt-4.1-mini jobfit match 55189170 55162188 --refresh
```
기록: 모델별 의도 판정 일치율, 인용 검증 실패 수, 순서·구간. 일치율 차이가 없으면 경량.

- [ ] **Step 3: 실험 Y2 — 수용 기준**: 스펙 03 10장. 미달이면 원인을 (판정 프롬프트 / 이력서 표현 / 점수 상수 / 의도 자체)로 분류해 고치고 다시 잰다. 점수 상수를 바꾸면 ADR-0017에 기록.

- [ ] **Step 4: 실험 Y3 — 교차 평가**: 같은 실행 결과에서 "(타 공고)" 지원자의 점수 분포를 기록한다.

- [ ] **Step 5: 캐시 확인**: `jobfit match 55189170 55162188 --refresh` 재실행 → API 호출 0회 (키 없이도 완료).

---

### Task 12: 기록

- [ ] 스펙 03 11장 (Y1–Y3 표, 진단), 10장 체크
- [ ] ADR-0017 상수 보정 결과, 판정 모델 기본값 (`DEFAULT_JUDGE_MODEL`)
- [ ] `docs/README.md` 진행 현황, `docs/architecture.md` 단계 표·데이터 디렉터리(`results/`)
- [ ] 커밋 `docs: 스펙 03 실험 결과와 스코어링 기본값 확정`
