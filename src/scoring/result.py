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
    use_derived: bool = True     # 모집분야에서 도출한 적합도 요건 반영 (ADR-0022)


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
    derived: bool = False        # 공고에 명시되지 않고 모집분야에서 도출한 요건


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
    tied_positions: bool = False  # 평가한 분야 점수가 모두 같음 — 대표 분야에 의미 없음

    @property
    def best(self) -> PositionScore:
        return next(p for p in self.positions if p.position == self.position)


class PostingRef(BaseModel):
    site: str
    posting_id: str
    title: str
    criteria_extracted_at: str


SCORING_VERSION = 2   # 점수 계산 방식이 바뀌면 올린다 — 예전 결과는 재사용하지 않음 (판정은 캐시)


class MatchResult(BaseModel):
    schema_version: int = 1
    scoring_version: int = 1     # 이 필드가 없던 결과는 1
    notes: list[str] = Field(default_factory=list)   # 공고 수준 안내 (정보 부족 등)
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
