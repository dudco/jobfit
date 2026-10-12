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
from .derive import JOB_CATEGORIES, needs_position_fit, position_fit_requirements
from .judge import judge
from .result import SCORING_VERSION, CandidateScore, MatchResult, PostingRef, Weights, load_result, save_result
from .score import aggregate, summarize
from .verify import judge_requirements


def target_positions(criteria: PostingCriteria, candidate: Candidate) -> list[Optional[str]]:
    """평가할 모집분야. 분야가 하나 이하면 [None](전체), 희망 분야가 공고에 있으면 그것만, 없으면 전부."""
    names = [p.name for p in criteria.positions]
    if len(names) <= 1:
        return [None]
    chosen = [p for p in candidate.desired_positions if p in names]
    return chosen or names


def applicable(criteria: PostingCriteria, position: Optional[str],
               extra: tuple[Requirement, ...] | list[Requirement] = ()) -> list[Requirement]:
    """분야에 적용되는 요건 (+ 도출 요건). 법정 우대(sensitive)는 판정·점수에서 뺀다 (ADR-0018)."""
    return [r for r in [*criteria.requirements, *extra]
            if not r.sensitive and (position is None or not r.positions or position in r.positions)]


def derived_requirements(criteria: PostingCriteria) -> list[Requirement]:
    return position_fit_requirements(criteria) if needs_position_fit(criteria) else []


def posting_notes(criteria: PostingCriteria, derived: list[Requirement]) -> list[str]:
    """정보가 부족한 공고를 드러낸다 — 점수를 얼마나 믿을 수 있는지 (스펙 05)."""
    if derived:
        return [f"공고 이미지에 직무 관련 요건이 없어, 모집분야 {len(derived)}개의 이름에서 '직무 적합도' 우대 요건을 "
                "도출해 반영함 — 공고에 명시된 요건이 아님 (가중치에서 끌 수 있음)"]
    jobish = [r for r in criteria.requirements if not r.sensitive
              and (r.category in JOB_CATEGORIES or r.positions)]
    if not jobish:
        return ["공고 이미지에 직무 관련 요건이 없어 공통 자격만으로 점수를 매김 — 지원자 간 점수 차이가 작을 수 있음"]
    return []


def score_candidate(llm: LLM, criteria: PostingCriteria, candidate: Candidate, *, model: str, today: str,
                    weights: Weights) -> CandidateScore:
    positions = target_positions(criteria, candidate)
    extra = derived_requirements(criteria)
    order = [*criteria.requirements, *extra]
    union: dict[str, Requirement] = {}
    for p in positions:
        for r in applicable(criteria, p, extra):
            union.setdefault(r.id, r)
    reqs = sorted(union.values(), key=order.index)
    named = [p for p in positions if p is not None]
    out = judge(llm, criteria, candidate, reqs, model=model, positions=named or None)   # 지원자당 1회
    judged = {j.requirement_id: j for j in judge_requirements(out, reqs, candidate, today=today)}
    per_position = [aggregate([judged[r.id] for r in applicable(criteria, p, extra)], p, weights) for p in positions]
    excluded = [r.text for r in criteria.requirements if r.sensitive]
    return _pick(candidate.id, candidate.name, per_position, excluded)


def _pick(candidate_id: str, name: str, per_position: list, excluded: list[str]) -> CandidateScore:
    def strength(ps):
        """점수가 같으면 판정이 더 강한 분야 (충족 수, 부분 수) — 부분과 확인 필요가 같은 점수라 생기는 동점을 가른다."""
        counted = [j for j in ps.judgments if j.credit is not None]
        return (round(ps.raw, 9), sum(j.status == "met" for j in counted), sum(j.status == "partial" for j in counted))

    best = max(per_position, key=strength)                            # 그래도 같으면 먼저 평가한 분야
    tied = len(per_position) > 1 and all(strength(ps) == strength(best) for ps in per_position)
    return CandidateScore(rank=0, candidate_id=candidate_id, name=name, score=best.score, raw=best.raw,
                          position=best.position, positions=per_position, summary=summarize(best, excluded),
                          excluded_sensitive=excluded, tied_positions=tied)


def match(ref: str, settings: Settings, *, llm: LLM, candidates_dir: Path, refresh: bool = False,
          log: Callable[[str], None] = print, weights: Weights = Weights()) -> MatchResult:
    posting_id = parse_rec_idx(ref)
    criteria = load_criteria(criteria_dir(settings.data_dir, SITE, posting_id))
    if criteria is None:
        raise RuntimeError(f"공고 {posting_id}의 조건이 없음 — 먼저 `jobfit extract {posting_id}`")
    existing = None if refresh else load_result(settings.data_dir, SITE, posting_id)
    if (existing is not None and existing.posting.criteria_extracted_at == criteria.extracted_at
            and existing.scoring_version == SCORING_VERSION):
        log(f"공고 {posting_id}: 기존 매칭 결과 사용 (--refresh로 다시)")
        return existing                                # 조건이 다시 추출됐으면 재사용하지 않는다
    if not criteria.suitable or not applicable(criteria, None):
        reason = "; ".join(criteria.warnings) or (
            "법정 우대 요건만 있음 (점수 미반영)" if criteria.requirements else "추출된 요건 0개")
        raise RuntimeError(f"공고 {posting_id}는 평가할 요건이 없음 — {reason}")
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
        scoring_version=SCORING_VERSION, notes=posting_notes(criteria, derived_requirements(criteria)),
    )
    save_result(settings.data_dir, result)
    return result


def rescore(result: MatchResult, weights: Weights) -> MatchResult:
    """저장된 판정으로 점수만 다시 계산한다 — LLM 호출 없음, 파일 저장 안 함 (ADR-0015, 스펙 04 F4)."""
    scores = []
    for c in result.candidates:
        per_position = [aggregate(p.judgments, p.position, weights) for p in c.positions]
        scores.append(_pick(c.candidate_id, c.name, per_position, c.excluded_sensitive))
    scores.sort(key=lambda s: (-s.raw, s.candidate_id))
    for i, s in enumerate(scores, start=1):
        s.rank = i
    return result.model_copy(update={"weights": weights, "candidates": scores})
