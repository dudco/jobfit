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
