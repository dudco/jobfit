from scoring.candidate import Candidate
from scoring.evaluate import evaluate_ranking
from scoring.result import (CandidateScore, MatchResult, PositionScore, PostingRef, RequirementJudgment,
                            Weights)


def pos(position, score, judgments=()):
    js = [RequirementJudgment(requirement_id=f"r{i}", text=t, priority="must", category="other", status=s)
          for i, (t, s) in enumerate(judgments, start=1)]
    return PositionScore(position=position, score=score, raw=score, must_met=0, must_total=1, preferred_met=0,
                         preferred_total=0, unmet_must=[], unknown=[], judgments=js)


def scored(cid, score, judgments=(), extra=()):
    positions = [pos(None, score, judgments), *extra]
    return CandidateScore(rank=0, candidate_id=cid, name=cid, score=score, raw=score, position=None,
                          positions=positions, summary=[], excluded_sensitive=[])


def cand(cid, label, posting="55", expected=()):
    return Candidate(id=cid, name=cid, meta={"target_posting": posting, "label": label,
                                             "expected": [{"requirement": r, "status": s} for r, s in expected]})


def result(*scores):
    return MatchResult(posting=PostingRef(site="saramin", posting_id="55", title="t", criteria_extracted_at="t"),
                       matched_at="t", model="m", weights=Weights(), candidates=list(scores))


def test_order_ranges_and_expected_agreement():
    r = result(scored("p", 90, [("공인영어성적 보유", "met")]), scored("q", 60), scored("m", 20),
               scored("other", 95))
    cands = [cand("p", "perfect", expected=[("공인 영어성적", "met")]), cand("q", "partial"),
             cand("m", "mismatch", expected=[("야간근무", "unmet")]), cand("other", "perfect", posting="99")]
    ev = evaluate_ranking(r, cands)
    assert ev.order_ok and ev.out_of_range == []
    assert (ev.agreed, ev.expected_total) == (1, 2)
    assert ev.disagreements == ["m: '야간근무' — 해당 요건 없음"]


def test_expected_judgment_found_in_other_evaluated_position():
    s = scored("q", 60, [("공통", "met")], extra=[pos("안전환경", 50, [("화공/안전/환경 전공", "unmet")])])
    ev = evaluate_ranking(result(s), [cand("q", "partial", expected=[("화공/안전", "unmet")])])
    assert (ev.agreed, ev.expected_total) == (1, 1)


def test_order_violation_and_range_reported():
    ev = evaluate_ranking(result(scored("p", 70), scored("q", 75), scored("m", 45)),
                          [cand("p", "perfect"), cand("q", "partial"), cand("m", "mismatch")])
    assert not ev.order_ok
    assert ev.out_of_range == ["p 70 (perfect ≥ 85)", "m 45 (mismatch < 40)"]
