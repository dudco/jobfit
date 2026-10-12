from scoring.candidate import Candidate
from scoring.judge import LLMJudgeOutput, LLMJudgment
from scoring.verify import judge_requirements

from .scoring_fixtures import make_requirement

CAND = Candidate(id="c", name="n", education=[{"level": "high_school", "school": "청주고"}],
                 experiences=[{"company": "A식품", "role": "포장", "start": "2022-01", "end": "2023-12"}],
                 declarations=["야간근무 가능"])


def out(*items):
    return LLMJudgeOutput(judgments=[LLMJudgment(requirement_id=i, status=s, quotes=list(q), reason="r",
                                                 relevant_experience=list(e)) for i, s, q, e in items])


def run(reqs, *items):
    return {x.requirement_id: x for x in judge_requirements(out(*items), reqs, CAND, today="2026-10")}


def test_quote_must_exist_in_rendered_resume_else_unknown():
    reqs = [make_requirement("r1", "야간근무"), make_requirement("r2", "운전면허")]
    got = run(reqs, ("r1", "met", ["L04 [자기 신고] 야간근무 가능"], []),   # 줄 번호가 붙어도 인정
              ("r2", "met", ["[자격증] 1종 보통"], []))                       # 이력서에 없음
    assert (got["r1"].status, got["r1"].flags, got["r1"].quotes) == ("met", [], ["[자기 신고] 야간근무 가능"])
    assert (got["r2"].status, got["r2"].flags) == ("unknown", ["quote_not_found"])


def test_quote_label_punctuation_is_ignored():
    """'[자기 신고] 야간근무 가능'을 '자기 신고: 야간근무 가능'으로 옮겨도 같은 줄이다 (Y1 관찰)."""
    got = run([make_requirement("r1", "야간근무")], ("r1", "met", ["자기 신고: 야간근무 가능"], []))
    assert (got["r1"].status, got["r1"].flags) == ("met", [])


def test_judgment_without_evidence_and_missing_or_unknown_ids():
    reqs = [make_requirement("r1", "a"), make_requirement("r2", "b")]
    got = run(reqs, ("r1", "unmet", [], []), ("r9", "met", [], []), ("r1", "met", [], []))
    assert (got["r1"].status, got["r1"].flags) == ("unknown", ["no_evidence"])
    assert (got["r2"].status, got["r2"].flags) == ("unknown", ["not_judged"])
    assert set(got) == {"r1", "r2"}


def test_unknown_and_not_applicable_need_no_evidence():
    reqs = [make_requirement("r1", "a"), make_requirement("r2", "b")]
    got = run(reqs, ("r1", "unknown", [], []), ("r2", "not_applicable", [], []))
    assert [(x.status, x.flags) for x in got.values()] == [("unknown", []), ("not_applicable", [])]


def test_education_rule_overrides_llm_when_below_minimum():
    reqs = [make_requirement("r1", "대졸", category="education", min_education="bachelor"),
            make_requirement("r2", "고졸", category="education", min_education="high_school")]
    got = run(reqs, ("r1", "met", ["[학력] 고등학교 · 청주고 · 졸업"], []),
              ("r2", "partial", ["[학력] 고등학교 · 청주고 · 졸업"], []))
    assert (got["r1"].status, got["r1"].rule) == ("unmet", "education_level")
    assert (got["r2"].status, got["r2"].rule) == ("partial", None)          # 수준 충족 → LLM 판정 유지


def test_experience_rule_computes_years_from_selected_jobs():
    reqs = [make_requirement("r1", "생산 경력 3년", category="experience", min_years=3)]
    got = run(reqs, ("r1", "met", ["[경력 1] A식품 · 포장 · 2022-01~2023-12"], [1]))
    assert (got["r1"].status, got["r1"].rule) == ("partial", "experience_years")
    assert "2.0년" in got["r1"].reason and "3년" in got["r1"].reason
