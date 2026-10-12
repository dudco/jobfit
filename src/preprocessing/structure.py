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
