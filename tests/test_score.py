import pytest

from scoring.result import RequirementJudgment, Weights
from scoring.score import aggregate, summarize


def j(rid, status, priority="must", text=None, quotes=()):
    return RequirementJudgment(requirement_id=rid, text=text or rid, priority=priority, category="other",
                               status=status, quotes=list(quotes))


def test_contributions_sum_to_raw_score_and_all_met_is_100():
    ps = aggregate([j("r1", "met"), j("r2", "met"), j("r3", "met", "preferred")], None)
    assert ps.score == 100
    assert sum(x.contribution for x in ps.judgments) == pytest.approx(ps.raw)


def test_must_only_met_without_preferred_strengths_is_70():
    ps = aggregate([j("r1", "met"), j("r2", "unmet", "preferred"), j("r3", "unmet", "preferred")], None)
    assert ps.score == 70


def test_unmet_must_applies_gate_but_unknown_does_not():
    unmet = aggregate([j("r1", "met"), j("r2", "unmet")], None)          # M=0.5, gate 0.8 → 40
    unknown = aggregate([j("r1", "met"), j("r2", "unknown")], None)      # M=0.75, gate 1 → 75
    assert (unmet.score, unknown.score) == (40, 75)
    assert unmet.unmet_must == ["r2"] and unknown.unknown == ["r2"]


def test_not_applicable_is_excluded_from_denominator():
    ps = aggregate([j("r1", "met"), j("r2", "not_applicable")], None)
    assert ps.score == 100 and ps.must_total == 1
    assert ps.judgments[1].credit is None and ps.judgments[1].contribution == 0


def test_no_preferred_means_base_is_must_average():
    assert aggregate([j("r1", "met"), j("r2", "partial")], None).score == 75


def test_custom_weights_rescore_without_llm():
    js = [j("r1", "met"), j("r2", "unmet", "preferred")]
    assert aggregate(js, None, Weights(must_share=0.5)).score == 50


def test_switched_off_derived_requirements_leave_no_trace_in_counts_or_summary():
    fit = j("p1", "unknown", "preferred", text="'재무' 직무 적합")
    fit.derived = True
    ps = aggregate([j("r1", "met"), fit], None, Weights(use_derived=False))
    assert ps.score == 100 and ps.unknown == [] and ps.preferred_total == 0
    assert not any("직무 적합" in line for line in summarize(ps, []))


def test_nothing_to_score_is_an_error():
    with pytest.raises(ValueError):
        aggregate([j("r1", "not_applicable")], None)


def test_summary_is_built_from_judgments():
    ps = aggregate([j("r1", "met", text="대졸"), j("r2", "unmet", text="공인영어성적", quotes=["[어학] 없음"]),
                    j("r3", "unknown", text="해외여행 결격사유 없음"), j("r4", "met", "preferred", text="회화")], None)
    lines = summarize(ps, excluded_sensitive=["장애인 우대"])
    assert lines[0] == "필수 3개 중 1개 충족 · 우대 1개 중 1개 충족"
    assert '미충족: [필수] 공인영어성적 (이력서: "[어학] 없음")' in lines
    assert "확인 필요: 해외여행 결격사유 없음" in lines
    assert lines[-1] == "법정 우대 1개는 점수에 반영하지 않음"
