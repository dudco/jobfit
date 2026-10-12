"""매칭 결과를 목업의 의도(meta)와 비교한다 — 평가 전용. 스코어링 경로는 이 모듈을 쓰지 않는다."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .candidate import Candidate
from .result import CandidateScore, MatchResult, RequirementJudgment

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


def _find(score: CandidateScore, requirement: str) -> RequirementJudgment | None:
    """대표 분야부터, 없으면 다른 평가 분야에서 요건 문구로 판정을 찾는다."""
    ordered = sorted(score.positions, key=lambda p: p.position != score.position)
    for p in ordered:
        for j in p.judgments:
            if _compact(requirement) in _compact(j.text):
                return j
    return None


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
        for e in meta[s.candidate_id].expected:
            ev.expected_total += 1
            hit = _find(s, e.requirement)
            if hit is None:
                ev.disagreements.append(f"{s.candidate_id}: '{e.requirement}' — 해당 요건 없음")
            elif hit.status == e.status:
                ev.agreed += 1
            else:
                ev.disagreements.append(f"{s.candidate_id}: '{e.requirement}' 의도 {e.status} / 판정 {hit.status}")
    return ev
