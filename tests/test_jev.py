"""판단 전용 모델(JEV) 실험 어댑터 (스펙 06). 실제 API는 호출하지 않는다."""
from types import SimpleNamespace

import pytest

pytest.importorskip("typesafe_sdk")      # 선택 의존성 [jev]

from scoring.candidate import Candidate, render_lines
from scoring.jev import STATUS_LABELS, CachedJev, build_questions, to_output
from scoring.verify import judge_requirements

from .scoring_fixtures import make_criteria, make_requirement

CAND = Candidate(id="c1", name="김", address="충북 청주시 흥덕구", declarations=["야간근무 가능"],
                 education=[{"level": "high_school", "school": "청주고"}])
REQS = [make_requirement("r1", "야간근무 가능자"), make_requirement("r2", "인근거주자", "preferred")]


def answer(choice, conf=0.9, probs=None):
    return SimpleNamespace(choice=choice, confidence=conf, probabilities=probs or {choice: conf})


def test_questions_ask_status_and_evidence_line_per_requirement():
    state, questions = build_questions(make_criteria(REQS), CAND, REQS, positions=None)
    assert set(questions) == {"r1__status", "r1__evidence", "r2__status", "r2__evidence"}
    assert set(questions["r1__status"].criteria) == set(STATUS_LABELS)
    lines = render_lines(CAND)
    evidence = questions["r1__evidence"].criteria
    assert list(evidence)[:len(lines)] == [f"L{i:02d}" for i in range(1, len(lines) + 1)]
    assert evidence["L01"] == lines[0] and "none" in evidence
    assert "야간근무 가능자" in str(questions["r1__status"].instructions)
    assert "resume" in state and "posting" in state


def test_output_quotes_come_from_chosen_resume_line_so_they_always_verify():
    answers = {"r1__status": answer("met"), "r1__evidence": answer("L04"),
               "r2__status": answer("met"), "r2__evidence": answer("none")}
    out, details = to_output(REQS, CAND, answers)
    got = {j.requirement_id: j for j in judge_requirements(out, REQS, CAND, today="2026-10")}
    assert got["r1"].status == "met" and got["r1"].quotes == ["[자기 신고] 야간근무 가능"]
    assert (got["r2"].status, got["r2"].flags) == ("unknown", ["no_evidence"])    # 근거 줄 없이 충족 → 확인 필요
    assert details["r1"]["confidence"] == 0.9


def test_cache_avoids_second_call(tmp_path):
    calls = []

    class Client:
        def system_one(self, state, questions, model=None):
            calls.append(1)
            return SimpleNamespace(model="jev-1.13.0", usage=SimpleNamespace(input_tokens=1000, output_tokens=0),
                                   answers={q: answer("unknown") for q in questions})

    jev = CachedJev(lambda: Client(), tmp_path, model="jev-latest")
    q = build_questions(make_criteria(REQS), CAND, REQS, positions=None)
    first = jev.ask(*q, tag="55-c1")
    second = jev.ask(*q, tag="55-c1")
    assert len(calls) == 1 and first == second
    assert first["usage"]["input_tokens"] == 1000 and first["answers"]["r1__status"]["choice"] == "unknown"


def test_experiment_compares_with_gpt_reference_and_computes_cascade(tmp_path):
    from scoring.experiment_jev import run_experiment

    from .fakes import FakeLLM
    from .test_scoring_service import REQS as SVC_REQS, by_declaration, person, settings, write_candidates, \
        write_criteria
    from scoring.service import match
    import dataclasses

    write_criteria(tmp_path, make_criteria(SVC_REQS))
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]), person("b", ["야간근무 불가"], label="mismatch"))
    s = dataclasses.replace(settings(tmp_path), candidates_dir=d)
    match("55", s, llm=FakeLLM(structured=[by_declaration] * 2), candidates_dir=d, log=lambda m: None)

    class Client:   # a: 야간 met(0.95), b: 야간 met(0.7) ← 기준(gpt)은 unmet. 인근거주는 둘 다 unknown(0.9)
        def system_one(self, state, questions, model=None):
            b = "야간근무 불가" in state["resume"]
            ans = {"r1__status": answer("met", 0.7 if b else 0.95), "r1__evidence": answer("L02"),
                   "r2__status": answer("unknown", 0.9), "r2__evidence": answer("none")}
            return SimpleNamespace(model="jev-1.13.0", usage=SimpleNamespace(input_tokens=2000, output_tokens=0),
                                   answers={q: ans[q] for q in questions})

    report = run_experiment("55", s, jev=CachedJev(lambda: Client(), tmp_path / "jc", model="jev-latest"),
                            thresholds=[0.6, 0.8], log=lambda m: None)
    assert report["agree_with_gpt"] == 0.75
    assert report["disagreements"] == [{"candidate": "b", "requirement": "야간근무", "gpt": "unmet", "jev": "met",
                                        "confidence": 0.7}]
    low, high = report["cascade"]
    assert (low["escalated"], low["agree_with_gpt"]) == (0, 0.75)     # 0.6 미만 없음 → 모두 JEV
    assert (high["escalated"], high["agree_with_gpt"]) == (1, 1.0)    # b만 gpt로 → 전부 일치
    assert report["input_tokens"] == 4000 and (tmp_path / "data" / "experiments" / "jev-55.json").exists()
