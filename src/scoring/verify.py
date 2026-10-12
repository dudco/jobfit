"""판정 검증과 규칙 보정 — 코드가 책임지는 부분 (ADR-0015).

1. 인용이 렌더링된 이력서에 있는지 확인 (없으면 unknown — 환각 방어)
2. 근거 없는 판정, 판정 누락, 모르는 id·중복 보정
3. 학력 서열·경력 연수는 규칙으로 (규칙이 LLM보다 우선)
"""
from __future__ import annotations

import re

from preprocessing.criteria import Requirement
from preprocessing.verify import clean_text, find_fragments, find_quote

from .candidate import Candidate, render
from .derive import DERIVED_FLAG
from .judge import LLMJudgeOutput, LLMJudgment
from .result import RequirementJudgment
from .rules import education_status, experience_years, years_status

LINE_NO = re.compile(r"^\s*L\d+\s*")
NEEDS_EVIDENCE = {"met", "partial", "unmet"}


LABEL_PUNCT = re.compile(r"[\[\]:：]")      # '[주소] 서울' ↔ '주소: 서울' — 줄 머리표 표기 차이는 무시


def _found(quote: str, text: str) -> bool:
    q, t = LABEL_PUNCT.sub(" ", quote), LABEL_PUNCT.sub(" ", text)
    return find_quote(q, t) is not None or find_fragments(q, t) is not None


def judge_requirements(out: LLMJudgeOutput, requirements: list[Requirement], candidate: Candidate,
                       *, today: str) -> list[RequirementJudgment]:
    text = render(candidate)
    by_id: dict[str, LLMJudgment] = {}
    for j in out.judgments:
        by_id.setdefault(j.requirement_id, j)          # 중복이면 첫 판정, 모르는 id는 아래에서 안 쓰임
    result = []
    for r in requirements:
        j = by_id.get(r.id)
        if j is None:
            status, quotes, reason, flags, picked = "unknown", [], "판정 누락", ["not_judged"], []
        else:
            quotes = [LINE_NO.sub("", clean_text(q)).strip() for q in j.quotes if q.strip()]
            status, reason, flags, picked = j.status, j.reason, [], j.relevant_experience
            if status == "unknown":
                quotes = [q for q in quotes if _found(q, text)]    # 점수에 영향 없음 — 틀린 인용만 버린다
            elif not all(_found(q, text) for q in quotes):
                status, flags = "unknown", ["quote_not_found"]
            elif status in NEEDS_EVIDENCE and not quotes:
                status, flags = "unknown", ["no_evidence"]
        rule = None
        if r.min_education not in (None, "none"):
            edu, why = education_status(candidate, r.min_education)
            if edu is not None:                         # 미달·정보 없음은 규칙이 정한다
                status, reason, rule = edu, why, "education_level"
        if rule is None and r.category == "experience" and r.min_years:
            have = experience_years(candidate, picked, today=today)
            status, rule = years_status(have, r.min_years), "experience_years"
            reason = f"관련 경력 {have:.1f}년 / 요구 {r.min_years:g}년"
        derived = DERIVED_FLAG in r.flags
        result.append(RequirementJudgment(
            requirement_id=r.id, text=r.text, priority=r.priority, category=r.category,
            status=status, quotes=quotes, reason=reason, rule=rule,
            flags=flags + ([DERIVED_FLAG] if derived else []), derived=derived,
        ))
    return result
