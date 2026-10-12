"""지원자 모델과 줄 번호 렌더링 (ADR-0016).

이 JSON은 '이력서 전처리 결과'라는 계약이다 — 스코어링은 원본 형식(PDF·DOCX·HTML·MD·이미지)을 모른다.
목업 데이터셋은 전처리를 손으로 대신한 결과다.

render()가 이력서의 유일한 '원문'이다. 판정 LLM은 이 텍스트만 보고, 근거 인용도 이 텍스트에서 확인한다.
source(출처)와 meta(평가용 의도 라벨)는 렌더링하지 않는다.
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


class CandidateSource(BaseModel):
    """이력서 출처. 원본 형식은 여기에만 기록하고 스코어링은 읽지 않는다 (ADR-0016)."""
    method: Literal["mock", "upload", "ats"] = "mock"
    format: Optional[str] = None              # pdf | docx | html | md | image
    file_sha256: Optional[str] = None
    extracted_text: Optional[str] = None      # 추출 텍스트 위치


class ExpectedJudgment(BaseModel):
    requirement: str                          # 요건 문구의 일부 ("공인영어성적")
    status: Status


class CandidateMeta(BaseModel):
    """평가 전용 — 렌더링·판정·점수 계산은 읽지 않는다."""
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
    source: CandidateSource = Field(default_factory=CandidateSource)
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
