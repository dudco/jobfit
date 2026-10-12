"""직무 요건이 없는 공고에서 모집분야 적합도 요건을 도출 (ADR-0022)."""
from scoring.derive import needs_position_fit, position_fit_requirements

from .scoring_fixtures import make_criteria, make_requirement

COMMON = [make_requirement("r1", "해외여행 결격사유 없음"), make_requirement("r2", "남성의 경우 병역필"),
          make_requirement("r3", "보훈 우대", priority="preferred", sensitive=True)]


def test_needed_only_when_posting_has_no_job_related_requirement():
    assert needs_position_fit(make_criteria(COMMON, positions=["재무운영 지원", "실험실 보조"]))
    with_exp = COMMON + [make_requirement("r4", "해당직무 경험", "preferred", "experience")]
    assert not needs_position_fit(make_criteria(with_exp, positions=["생산직"]))
    scoped = COMMON + [make_requirement("r4", "화공 전공", category="education", positions=["공정"])]
    assert not needs_position_fit(make_criteria(scoped, positions=["공정", "재무"]))
    assert not needs_position_fit(make_criteria(COMMON))                  # 모집분야가 없으면 도출할 재료가 없음


def test_requirement_covering_all_positions_is_not_job_specific():
    everywhere = COMMON + [make_requirement("r4", "대졸", category="education", positions=["A", "B"])]
    assert needs_position_fit(make_criteria(everywhere, positions=["A", "B"]))


def test_one_preferred_requirement_per_position_marked_as_derived():
    crit = make_criteria(COMMON, positions=["재무운영 지원", "실험실 보조"])
    crit.positions[1].duties = "분석 시료 준비"
    reqs = position_fit_requirements(crit)
    assert [(r.id, r.priority, r.positions) for r in reqs] == [
        ("p1", "preferred", ["재무운영 지원"]), ("p2", "preferred", ["실험실 보조"])]
    assert reqs[1].text == "'실험실 보조'(분석 시료 준비) 직무 관련 경력·전공·자격"
    assert all(r.flags == ["derived_from_position"] and r.evidence.slice_index is None for r in reqs)
