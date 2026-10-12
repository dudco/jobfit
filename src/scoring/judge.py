"""요건별 판정 — 스코어링에서 LLM이 맡는 유일한 부분 (ADR-0015). 숫자 점수는 내지 않는다."""
from __future__ import annotations

from pydantic import BaseModel

from llm import LLM
from preprocessing.criteria import PostingCriteria, Requirement

from .candidate import Candidate, Status, render

JUDGE_SYSTEM = """당신은 채용 서류 심사자다. 공고의 요건 목록과 지원자 이력서(줄 번호가 붙은 텍스트)를 받아, 요건마다 이력서가 그 요건을 충족하는지 판정한다.

판정 상태:
- met: 이력서에 요건을 충족한다는 사실이 있다.
- partial: 일부만 충족한다 (기간·수준 부족, 인접 분야, 기술·키워드를 나열만 하고 경력·학력·자격으로 뒷받침하지 않음).
- unmet: 이력서가 요건과 반대되는 사실을 말한다 (다른 전공, 불가하다고 밝힘, 기한을 넘김, 보유하지 않았다고 밝힘 등).
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
