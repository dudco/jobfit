import json

import pytest

from preprocessing.criteria import criteria_dir, save_criteria
from scoring.candidate import Candidate
from scoring.judge import LLMJudgeOutput, LLMJudgment
from scoring.result import Weights, load_result
from scoring.service import applicable, match, rescore, target_positions
from settings import Settings

from .fakes import FakeLLM
from .scoring_fixtures import make_criteria, make_requirement


def quiet(_msg):
    pass


def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", judge_model="j")


def write_criteria(tmp_path, criteria):
    save_criteria(criteria_dir(tmp_path / "data", "saramin", criteria.source.posting_id), criteria)


def write_candidates(tmp_path, *cands):
    d = tmp_path / "cands"
    d.mkdir(exist_ok=True)
    for c in cands:
        (d / f"{c['id']}.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    return d


def person(cid, declarations=(), desired=(), label="perfect"):
    return {"id": cid, "name": cid, "declarations": list(declarations), "desired_positions": list(desired),
            "meta": {"target_posting": "55", "label": label}}


def by_declaration(user: str) -> LLMJudgeOutput:
    """결정적 판정 대역: [자기 신고] 줄에 요건 문구가 있으면 met, 그 줄에 '불가'가 있으면 unmet, 없으면 unknown."""
    head, resume = user.split("# 이력서", 1)
    lines = [l.split(" ", 1)[1] for l in resume.strip().splitlines()]
    out = []
    for rl in (l for l in head.splitlines() if l.startswith("- r")):
        rid, text = rl[2:].split(" ", 1)[0], rl.rsplit("] ", 1)[1]
        hit = next((l for l in lines if l.startswith("[자기 신고]") and text in l), None)
        status = "unknown" if hit is None else ("unmet" if "불가" in hit else "met")
        out.append(LLMJudgment(requirement_id=rid, status=status, quotes=[hit] if hit else [], reason="r",
                               relevant_experience=[]))
    return LLMJudgeOutput(judgments=out)


REQS = [make_requirement("r1", "야간근무"), make_requirement("r2", "인근거주", priority="preferred"),
        make_requirement("r3", "보훈", priority="preferred", sensitive=True)]


def test_ranks_by_score_and_saves(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]), person("b", ["야간근무 가능", "인근거주"]),
                         person("c", ["야간근무 불가"], label="mismatch"))
    result = match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration] * 3), candidates_dir=d,
                   log=quiet)
    # a: 야간 met, 인근 unknown(0.5) → 70+15 / c: 야간 unmet → (0 + 0.3·0.5)·0.8
    assert [(c.candidate_id, c.score, c.rank) for c in result.candidates] == [("b", 100, 1), ("a", 85, 2), ("c", 12, 3)]
    for c in result.candidates:
        assert sum(j.contribution for j in c.best.judgments) == pytest.approx(c.raw)
    assert load_result(tmp_path / "data", "saramin", "55") == result


def test_sensitive_requirements_are_not_sent_or_scored(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]))
    seen = []
    llm = FakeLLM(structured=[lambda user: (seen.append(user), by_declaration(user))[1]])
    result = match("55", settings(tmp_path), llm=llm, candidates_dir=d, log=quiet)
    assert "보훈" not in seen[0]
    assert result.candidates[0].excluded_sensitive == ["보훈"]
    assert {x.requirement_id for x in result.candidates[0].best.judgments} == {"r1", "r2"}


def test_meta_label_does_not_change_scores(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    scores = []
    for label in ("perfect", "mismatch"):
        d = write_candidates(tmp_path, person("a", ["야간근무 가능"], label=label))
        r = match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration]), candidates_dir=d,
                  refresh=True, log=quiet)
        scores.append(r.candidates[0].raw)
    assert scores[0] == scores[1]


def test_positions_desired_then_best(tmp_path):
    reqs = [make_requirement("r1", "야간근무"), make_requirement("r2", "화공", positions=["공정"]),
            make_requirement("r3", "기계", positions=["설비"])]
    crit = make_criteria(reqs, positions=["공정", "설비", "재무"])
    desired = Candidate.model_validate(person("a", ["야간근무 가능", "기계"], desired=["설비", "없는분야"]))
    assert target_positions(crit, desired) == ["설비"]
    assert target_positions(crit, Candidate.model_validate(person("b"))) == ["공정", "설비", "재무"]
    assert [r.id for r in applicable(crit, "공정")] == ["r1", "r2"]
    write_criteria(tmp_path, crit)
    d = write_candidates(tmp_path, person("b", ["야간근무 가능", "기계"]))
    result = match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration]), candidates_dir=d, log=quiet)
    top = result.candidates[0]
    # 공정: r1 met·r2 unknown → 75 / 설비: r1·r3 met → 100 / 재무: r1 met → 100 — 동점이면 먼저 평가한 분야
    assert (top.position, top.score) == ("설비", 100)
    assert [p.score for p in top.positions] == [75, 100, 100]


def test_reuses_saved_result_without_llm_unless_refresh(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]))
    match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration]), candidates_dir=d, log=quiet)
    llm = FakeLLM()
    match("55", settings(tmp_path), llm=llm, candidates_dir=d, log=quiet)
    assert llm.calls == []


def test_missing_or_unsuitable_criteria(tmp_path):
    d = write_candidates(tmp_path, person("a"))
    with pytest.raises(RuntimeError, match="jobfit extract 55"):
        match("55", settings(tmp_path), llm=FakeLLM(), candidates_dir=d, log=quiet)
    unsuitable = make_criteria([], suitable=False)
    unsuitable.warnings = ["스냅샷에 본문 이미지가 없음"]
    write_criteria(tmp_path, unsuitable)
    with pytest.raises(RuntimeError, match="평가할 요건이 없음 — 스냅샷에 본문 이미지가 없음"):
        match("55", settings(tmp_path), llm=FakeLLM(), candidates_dir=d, log=quiet)
    write_criteria(tmp_path, make_criteria([make_requirement("r1", "보훈", sensitive=True)]))
    with pytest.raises(RuntimeError, match="평가할 요건"):
        match("55", settings(tmp_path), llm=FakeLLM(), candidates_dir=d, log=quiet)


def test_unseen_job_family_with_years_rule(tmp_path):
    """코드에 없는 직군(바리스타)도 요건 데이터만으로 점수가 나온다 — 일반화 스모크."""
    reqs = [make_requirement("r1", "바리스타 경력 2년 이상", category="experience", min_years=2)]
    write_criteria(tmp_path, make_criteria(reqs, posting_id="77"))
    d = write_candidates(tmp_path, {"id": "x", "name": "x", "experiences": [
        {"company": "카페", "role": "바리스타", "start": "2025-01", "end": "2025-12"}]})
    out = LLMJudgeOutput(judgments=[LLMJudgment(requirement_id="r1", status="met",
                                                quotes=["[경력 1] 카페 · 바리스타 · 2025-01~2025-12"], reason="r",
                                                relevant_experience=[1])])
    result = match("77", settings(tmp_path), llm=FakeLLM(structured=[out]), candidates_dir=d, log=quiet)
    j = result.candidates[0].best.judgments[0]
    assert (j.status, j.rule, result.candidates[0].score) == ("unmet", "experience_years", 0)   # 1년/2년 < 0.6


def test_saved_result_is_reused_only_for_the_same_criteria(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]))
    match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration]), candidates_dir=d, log=quiet)
    crit = make_criteria(REQS)
    crit.extracted_at = "t2"                             # 다시 추출된 조건
    write_criteria(tmp_path, crit)
    llm = FakeLLM(structured=[by_declaration])
    result = match("55", settings(tmp_path), llm=llm, candidates_dir=d, log=quiet)
    assert llm.calls and result.posting.criteria_extracted_at == "t2"


def test_rescore_changes_ranking_without_llm(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]), person("b", ["인근거주", "야간근무 불가"]))
    result = match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration] * 2), candidates_dir=d,
                   log=quiet)
    assert [c.candidate_id for c in result.candidates] == ["a", "b"]           # a 85, b (0+0.3)·0.8=24
    again = rescore(result, Weights(must_share=0.0, gate=1.0))                  # 우대만 본다
    assert [c.candidate_id for c in again.candidates] == ["b", "a"]
    assert again.weights.must_share == 0.0 and [c.rank for c in again.candidates] == [1, 2]
    for c in again.candidates:
        assert sum(j.contribution for j in c.best.judgments) == pytest.approx(c.raw)
    assert load_result(tmp_path / "data", "saramin", "55") == result           # 저장본은 그대로


COMMON_ONLY = [make_requirement("r1", "야간근무"), make_requirement("r3", "보훈", priority="preferred", sensitive=True)]


def by_declaration_and_fit(user: str) -> LLMJudgeOutput:
    """by_declaration + 도출 요건(p*)은 자기 신고에 분야 이름이 있으면 met."""
    out = by_declaration(user)
    head, resume = user.split("# 이력서", 1)
    for line in (l for l in head.splitlines() if l.startswith("- p")):
        rid, name = line[2:].split(" ", 1)[0], line.split("'")[1]
        hit = next((l.split(" ", 1)[1] for l in resume.strip().splitlines() if f"[자기 신고] {name}" in l), None)
        out.judgments.append(LLMJudgment(requirement_id=rid, status="met" if hit else "unknown",
                                         quotes=[hit] if hit else [], reason="r", relevant_experience=[]))
    return out


def test_posting_without_job_requirements_scores_position_fit(tmp_path):
    write_criteria(tmp_path, make_criteria(COMMON_ONLY, positions=["재무", "실험"]))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능", "재무"]), person("b", ["야간근무 가능"]))
    result = match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration_and_fit] * 2), candidates_dir=d,
                   log=quiet)
    a, b = result.candidates
    assert (a.candidate_id, a.score, a.position, a.tied_positions) == ("a", 100, "재무", False)
    assert (b.candidate_id, b.score, b.tied_positions) == ("b", 85, True)            # 적합도 확인 필요 → 전 분야 동일
    fit = next(j for j in a.best.judgments if j.requirement_id == "p1")
    assert fit.derived and "derived_from_position" in fit.flags
    assert any("모집분야" in n and "도출" in n for n in result.notes)
    off = rescore(result, Weights(use_derived=False))                               # 끄면 공통 자격만
    assert [c.score for c in off.candidates] == [100, 100]


def test_posting_with_job_requirements_is_unchanged(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS + [make_requirement("r4", "생산 경험", "preferred", "experience")],
                                           positions=["생산직"]))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]))
    seen = []
    llm = FakeLLM(structured=[lambda user: (seen.append(user), by_declaration(user))[1]])
    result = match("55", settings(tmp_path), llm=llm, candidates_dir=d, log=quiet)
    assert "- p1" not in seen[0] and result.notes == []


def test_old_results_are_recomputed_after_scoring_changes(tmp_path):
    write_criteria(tmp_path, make_criteria(REQS))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]))
    first = match("55", settings(tmp_path), llm=FakeLLM(structured=[by_declaration]), candidates_dir=d, log=quiet)
    from scoring.result import save_result
    save_result(tmp_path / "data", first.model_copy(update={"scoring_version": 1}))   # 예전 방식으로 만든 결과
    llm = FakeLLM(structured=[by_declaration])
    match("55", settings(tmp_path), llm=llm, candidates_dir=d, log=quiet)
    assert llm.calls
