"""스코어링 오케스트레이션. CLI·API가 같은 함수를 호출한다 (ADR-0002).

입력은 criteria.json과 지원자 JSON(이력서 전처리 결과)뿐 — 공고 이미지·HTML은 읽지 않는다.
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
    """평가할 모집분야. 분야가 하나 이하면 [None](전체), 희망 분야가 공고에 있으면 그것만, 없으면 전부."""
    names = [p.name for p in criteria.positions]
    if len(names) <= 1:
        return [None]
    chosen = [p for p in candidate.desired_positions if p in names]
    return chosen or names


def applicable(criteria: PostingCriteria, position: Optional[str]) -> list[Requirement]:
    """분야에 적용되는 요건. 법정 우대(sensitive)는 판정·점수에서 뺀다 (ADR-0018)."""
    return [r for r in criteria.requirements
            if not r.sensitive and (position is None or not r.positions or position in r.positions)]


def score_candidate(llm: LLM, criteria: PostingCriteria, candidate: Candidate, *, model: str, today: str,
                    weights: Weights) -> CandidateScore:
    positions = target_positions(criteria, candidate)
    union: dict[str, Requirement] = {}
    for p in positions:
        for r in applicable(criteria, p):
            union.setdefault(r.id, r)
    reqs = sorted(union.values(), key=criteria.requirements.index)
    named = [p for p in positions if p is not None]
    out = judge(llm, criteria, candidate, reqs, model=model, positions=named or None)   # 지원자당 1회
    judged = {j.requirement_id: j for j in judge_requirements(out, reqs, candidate, today=today)}
    per_position = [aggregate([judged[r.id] for r in applicable(criteria, p)], p, weights) for p in positions]
    best = max(per_position, key=lambda ps: ps.raw)                   # 동점이면 먼저 평가한 분야
    excluded = [r.text for r in criteria.requirements if r.sensitive]
    return CandidateScore(rank=0, candidate_id=candidate.id, name=candidate.name, score=best.score, raw=best.raw,
                          position=best.position, positions=per_position, summary=summarize(best, excluded),
                          excluded_sensitive=excluded)


def match(ref: str, settings: Settings, *, llm: LLM, candidates_dir: Path, refresh: bool = False,
          log: Callable[[str], None] = print, weights: Weights = Weights()) -> MatchResult:
    posting_id = parse_rec_idx(ref)
    criteria = load_criteria(criteria_dir(settings.data_dir, SITE, posting_id))
    if criteria is None:
        raise RuntimeError(f"공고 {posting_id}의 조건이 없음 — 먼저 `jobfit extract {posting_id}`")
    existing = None if refresh else load_result(settings.data_dir, SITE, posting_id)
    if existing is not None and existing.posting.criteria_extracted_at == criteria.extracted_at:
        log(f"공고 {posting_id}: 기존 매칭 결과 사용 (--refresh로 다시)")
        return existing                                # 조건이 다시 추출됐으면 재사용하지 않는다
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


def rescore(result: MatchResult, weights: Weights) -> MatchResult:
    """저장된 판정으로 점수만 다시 계산한다 — LLM 호출 없음, 파일 저장 안 함 (ADR-0015, 스펙 04 F4)."""
    scores = []
    for c in result.candidates:
        per_position = [aggregate(p.judgments, p.position, weights) for p in c.positions]
        best = max(per_position, key=lambda ps: ps.raw)
        scores.append(c.model_copy(update={
            "score": best.score, "raw": best.raw, "position": best.position, "positions": per_position,
            "summary": summarize(best, c.excluded_sensitive)}))
    scores.sort(key=lambda s: (-s.raw, s.candidate_id))
    for i, s in enumerate(scores, start=1):
        s.rank = i
    return result.model_copy(update={"weights": weights, "candidates": scores})
