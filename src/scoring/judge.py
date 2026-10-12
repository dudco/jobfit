"""요건별 판정 — 스코어링에서 LLM이 맡는 유일한 부분 (ADR-0015). 숫자 점수는 내지 않는다."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from llm import LLM
from preprocessing.criteria import PostingCriteria, Requirement

from .candidate import Candidate, Status, render

JUDGE_SYSTEM = """당신은 채용 서류 심사자다. 공고의 요건 목록과 지원자 이력서(줄 번호가 붙은 텍스트)를 받아, 요건마다 이력서가 그 요건을 충족하는지 판정한다.

판정 상태:
- met: 이력서에 요건을 충족한다는 사실이 있다.
- partial: 경력·경험·기술 요건에서 기간·수준이 모자라거나 인접 분야의 경험만 있다. 또는 [기술] 줄에만 있고 경력·학력·자격으로 뒷받침되지 않는다.
- unmet: 이력서가 요건과 어긋나는 사실을 말한다 — 정해진 목록(전공·자격 등)에 없는 것만 있음, 요건 문구의 기한·조건을 벗어남, 불가하다고 밝힘, 보유하지 않았다고 밝힘. 목록이나 기한이 정해진 요건은 가깝더라도 partial이 아니라 unmet이다.
- unknown: 이력서에 판단할 정보가 아예 없다. 정보가 없다는 이유로 unmet을 주지 않는다. 단, 학력란이 있는데 요구 전공·학위가 없으면 unknown이 아니라 unmet이다.
- not_applicable: 요건의 대상 조건("~의 경우")에 지원자가 해당하지 않음이 이력서로 확인된다.

규칙:
1. 이력서에 쓰인 사실만으로 판단한다. 추측하지 않는다.
2. 같은 뜻의 다른 표현, 상위·하위 개념을 인정한다 (학과·자격·직무·지명이 달라도 같은 계열·같은 지역이면 충족).
3. 학력 요건은 그 수준 이상이면 충족이다 (학사·석사는 고등학교 졸업 이상을 충족한다). 요건 문구 안의 기한·단서(졸업 예정 시점, 유효 기간 등)도 판정에 포함한다.
4. [기술] 줄에만 있는 내용은 partial을 넘지 않는다.
5. 거주지·통근 관련 요건은 '근무지'를 기준으로 판단한다: 근무지와 같은 시·군이면 met, 통근 가능한 인접 시·군이면 partial, 그 밖이면 unmet.
6. 지원자는 '평가 모집분야'에 지원한 것으로 본다. 대상 조건이 모집분야·직무 계열을 가리키면("엔지니어 직무 지원자의 경우") 평가 모집분야로 판단한다 — 요건의 모집분야 범위에 평가 모집분야가 있으면 대상이다.
7. met·partial·unmet에는 근거 인용(quotes)을 1개 이상 넣는다. 인용은 이력서 한 줄의 내용을 그대로 옮기되 줄 번호(L01 등)는 빼고, 여러 줄을 이어 붙이지 않는다.
8. reason은 한국어 한 문장.
9. experience 유형 요건이면 관련 있는 경력 번호([경력 N]의 N)를 relevant_experience에 넣는다. 다른 유형이면 빈 목록.
10. 요건마다 정확히 하나의 판정을 낸다. requirement_id는 주어진 id를 그대로 쓴다.
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


def context_lines(criteria: PostingCriteria, positions: Optional[list[str]]) -> list[str]:
    """판정에 필요한 공고 맥락 — 근무지('인근거주' 판단)와 평가 모집분야('~지원자의 경우' 판단).
    모두 공고 이미지에서 추출한 값이다 (ADR-0008)."""
    lines = []
    raw = [*criteria.conditions.locations, *(p.location for p in criteria.positions if p.location)]
    places = list(dict.fromkeys(part.strip() for item in raw for part in item.split(" / ") if part.strip()))
    if places:
        lines.append("근무지: " + " / ".join(places))
    shown = [p for p in criteria.positions if not positions or p.name in positions]
    if shown:
        lines += ["", "# 평가 모집분야"]
        for p in shown:
            detail = (f": {p.duties}" if p.duties else "") + (f" ({p.location})" if p.location else "")
            lines.append(f"- {p.name}{detail}")
    return lines


def build_prompt(criteria: PostingCriteria, requirements: list[Requirement], candidate: Candidate,
                 positions: Optional[list[str]] = None) -> str:
    company = f" ({criteria.company})" if criteria.company else ""
    return "\n".join([
        f"# 공고: {criteria.title}{company}", f"직군: {criteria.job_family}",
        *context_lines(criteria, positions), "",
        "# 요건", *[requirement_line(r) for r in requirements], "",
        "# 이력서", render(candidate),
    ])


def judge(llm: LLM, criteria: PostingCriteria, candidate: Candidate, requirements: list[Requirement],
          *, model: str, positions: Optional[list[str]] = None) -> LLMJudgeOutput:
    user = build_prompt(criteria, requirements, candidate, positions)
    return llm.structured(model=model, system=JUDGE_SYSTEM, user=user,
                          schema=LLMJudgeOutput, tag=f"judge-{criteria.source.posting_id}-{candidate.id}")
