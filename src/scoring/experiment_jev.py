"""스펙 06 실험: 판단 전용 모델(JEV) 판정을 gpt-4.1 판정(기준)·목업 의도와 비교하고, 단계식 판정(확신도가 낮으면
gpt-4.1로 넘김)의 일치율·비용을 계산한다. 결과는 data/experiments/에 저장하고, 매칭 결과(ranking.json)는 바꾸지 않는다.
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from crawler.service import SITE
from preprocessing.criteria import criteria_dir, load_criteria
from settings import Settings

from .candidate import Candidate, load_candidates
from .evaluate import evaluate_ranking
from .jev import PRICE_PER_MTOK, CachedJev, build_questions, to_output
from .result import MatchResult, PostingRef, Weights, load_result
from .service import posting_notes, derived_requirements, score_candidate

GPT_COST_PER_CANDIDATE = 0.0125   # gpt-4.1 판정 1회 추정 (스펙 03: 24회 ≈ $0.3)


def _compact(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _statuses(result: MatchResult) -> dict[tuple[str, str], str]:
    out = {}
    for c in result.candidates:
        for p in c.positions:
            for j in p.judgments:
                out.setdefault((c.candidate_id, j.requirement_id), j.status)
    return out


def _texts(result: MatchResult) -> dict[str, str]:
    return {j.requirement_id: j.text for c in result.candidates for p in c.positions for j in p.judgments}


def _expected_agreement(statuses: dict, texts: dict, candidates: list[Candidate], posting_id: str) -> tuple[int, int]:
    agreed = total = 0
    for c in candidates:
        if not c.meta or c.meta.target_posting != posting_id:
            continue
        for e in c.meta.expected:
            total += 1
            rid = next((r for r, t in texts.items() if _compact(e.requirement) in _compact(t)), None)
            agreed += rid is not None and statuses.get((c.id, rid)) == e.status
    return agreed, total


def _spearman(a: list[float], b: list[float]) -> float:
    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    if len(set(ra)) < 2 or len(set(rb)) < 2:
        return float("nan")
    return statistics.correlation(ra, rb)


def run_experiment(posting_id: str, settings: Settings, *, jev: CachedJev, thresholds: list[float],
                   log: Callable[[str], None] = print) -> dict:
    criteria = load_criteria(criteria_dir(settings.data_dir, SITE, posting_id))
    reference = load_result(settings.data_dir, SITE, posting_id)
    if criteria is None or reference is None:
        raise RuntimeError(f"공고 {posting_id}: 조건과 기준 매칭 결과가 필요함 — 먼저 `jobfit match {posting_id}`")
    candidates = load_candidates(settings.candidates_dir)
    today = reference.matched_at[:7]
    records: dict[str, dict] = {}
    details: dict[str, dict] = {}

    def judge_fn(cand: Candidate):
        def fn(crit, candidate, requirements, positions):
            state, questions = build_questions(crit, candidate, requirements, positions)
            rec = jev.ask(state, questions, tag=f"{posting_id}-{candidate.id}")
            records[candidate.id] = rec
            out, det = to_output(requirements, candidate, rec["answers"])
            details[candidate.id] = det
            return out
        return fn

    scores = []
    for c in candidates:
        log(f"공고 {posting_id}: {c.id} JEV 판정")
        scores.append(score_candidate(None, criteria, c, model=jev.model, today=today, weights=reference.weights,
                                      judge_fn=judge_fn(c)))
    scores.sort(key=lambda s: (-s.raw, s.candidate_id))
    for i, s in enumerate(scores, start=1):
        s.rank = i
    jev_result = MatchResult(
        posting=PostingRef(site=SITE, posting_id=posting_id, title=criteria.title,
                           criteria_extracted_at=criteria.extracted_at),
        matched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), model=jev.model,
        weights=reference.weights, candidates=scores, notes=posting_notes(criteria, derived_requirements(criteria)))

    ref_st, jev_st, texts = _statuses(reference), _statuses(jev_result), _texts(reference)
    common = [k for k in jev_st if k in ref_st]
    agree_ref = sum(jev_st[k] == ref_st[k] for k in common)
    ev_ref, ev_jev = evaluate_ranking(reference, candidates), evaluate_ranking(jev_result, candidates)
    ref_score = {c.candidate_id: c.raw for c in reference.candidates}
    ids = [c.candidate_id for c in jev_result.candidates if c.candidate_id in ref_score]

    tokens = sum(r["usage"]["input_tokens"] or 0 for r in records.values())
    jev_cost = tokens / 1_000_000 * PRICE_PER_MTOK
    cascade = []
    for t in thresholds:
        escalated = {cid for cid, det in details.items() if any(d["confidence"] < t for d in det.values())}
        final = {k: (ref_st[k] if k[0] in escalated and k in ref_st else v) for k, v in jev_st.items()}
        agreed, total = _expected_agreement(final, texts, candidates, posting_id)
        cascade.append({
            "threshold": t, "escalated": len(escalated), "candidates": len(details),
            "agree_with_gpt": sum(final[k] == ref_st[k] for k in common) / max(len(common), 1),
            "expected_agreed": agreed, "expected_total": total,
            "cost_usd": round(jev_cost + len(escalated) * GPT_COST_PER_CANDIDATE, 4),
        })
    report = {
        "posting_id": posting_id, "jev_model": sorted({r["model"] for r in records.values()}),
        "judgments": len(common), "agree_with_gpt": agree_ref / max(len(common), 1),
        "disagreements": [{"candidate": k[0], "requirement": texts.get(k[1], k[1]), "gpt": ref_st[k], "jev": jev_st[k],
                           "confidence": round(details.get(k[0], {}).get(k[1], {}).get("confidence", float("nan")), 3)}
                          for k in common if jev_st[k] != ref_st[k]],
        "gpt": {"order_ok": ev_ref.order_ok, "out_of_range": ev_ref.out_of_range,
                "expected": [ev_ref.agreed, ev_ref.expected_total]},
        "jev": {"order_ok": ev_jev.order_ok, "out_of_range": ev_jev.out_of_range,
                "expected": [ev_jev.agreed, ev_jev.expected_total],
                "scores": {c.candidate_id: c.score for c in jev_result.candidates},
                "tied_positions": sum(c.tied_positions for c in jev_result.candidates),
                "no_evidence": sum("no_evidence" in j.flags for c in jev_result.candidates
                                   for p in c.positions for j in p.judgments)},
        "spearman_vs_gpt": _spearman([ref_score[i] for i in ids], [c.raw for c in jev_result.candidates
                                                                  if c.candidate_id in ref_score]),
        "input_tokens": tokens, "jev_cost_usd": round(jev_cost, 6),
        "latency_s_median": statistics.median([r["latency_s"] for r in records.values()]) if records else None,
        "confidence_median": statistics.median([d["confidence"] for det in details.values() for d in det.values()])
        if details else None,
        "cascade": cascade,
    }
    out_dir = settings.data_dir / "experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"jev-{posting_id}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
    return report
