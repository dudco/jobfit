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
    picked = set(indices)
    spans = sorted(
        (_month(x.start), _month(x.end or today) + 1)
        for i, x in enumerate(c.experiences, start=1) if i in picked
    )
    months = 0
    cur: Optional[list[int]] = None
    for start, end in spans:
        if cur is None or start > cur[1]:
            if cur is not None:
                months += cur[1] - cur[0]
            cur = [start, end]
        else:
            cur[1] = max(cur[1], end)
    if cur is not None:
        months += cur[1] - cur[0]
    return months / 12


def years_status(have: float, need: float) -> Status:
    ratio = have / need if need > 0 else 1.0
    return "met" if ratio >= 1 else "partial" if ratio >= PARTIAL_RATIO else "unmet"
