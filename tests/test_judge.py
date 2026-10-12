from openai.lib._pydantic import to_strict_json_schema

from scoring.candidate import Candidate
from scoring.judge import LLMJudgeOutput, build_prompt, judge

from .fakes import FakeLLM
from .scoring_fixtures import make_criteria, make_requirement

CAND = Candidate(id="c9", name="박", education=[{"level": "high_school", "school": "s"}],
                 meta={"target_posting": "55", "label": "mismatch"})


def test_output_schema_is_openai_strict_compatible():
    assert to_strict_json_schema(LLMJudgeOutput)["additionalProperties"] is False


def test_prompt_lists_requirements_with_scope_and_rendered_resume_only():
    reqs = [make_requirement("r1", "고등학교 졸업 이상"), make_requirement("r2", "화공 전공", positions=["공정"])]
    prompt = build_prompt(make_criteria(reqs), reqs, CAND)
    assert "- r1 [필수 · other · 모집분야: 전체] 고등학교 졸업 이상" in prompt
    assert "- r2 [필수 · other · 모집분야: 공정] 화공 전공" in prompt
    assert "L02 [학력] 고등학교 · s · 졸업" in prompt
    assert "mismatch" not in prompt


def test_prompt_gives_workplace_and_evaluated_positions_as_context():
    """'인근거주'·'~지원자의 경우'처럼 공고 맥락이 있어야 판정할 수 있는 요건 (스펙 03 실험 Y1 진단)."""
    reqs = [make_requirement("r1", "인근거주자 우대", priority="preferred")]
    crit = make_criteria(reqs, positions=["공정", "재무"])
    crit.positions[0].location, crit.positions[0].duties = "울산 (공장)", "생산기획"
    crit.conditions.locations = ["충북 청주시 흥덕구"]
    prompt = build_prompt(crit, reqs, CAND, positions=["공정"])
    assert "근무지: 충북 청주시 흥덕구 / 울산 (공장)" in prompt
    assert "# 평가 모집분야" in prompt and "- 공정: 생산기획 (울산 (공장))" in prompt
    assert "- 재무" not in prompt
    whole = build_prompt(crit, reqs, CAND)                       # 분야를 정하지 않으면 공고의 모든 분야
    assert "- 공정: 생산기획 (울산 (공장))" in whole and "- 재무" in whole


def test_judge_calls_structured_once_with_cache_tag():
    reqs = [make_requirement("r1", "고등학교 졸업 이상")]
    llm = FakeLLM(structured=[LLMJudgeOutput(judgments=[])])
    judge(llm, make_criteria(reqs), CAND, reqs, model="m")
    assert llm.calls == [("structured", "judge-55-c9")]
