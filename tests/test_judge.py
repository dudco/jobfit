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


def test_judge_calls_structured_once_with_cache_tag():
    reqs = [make_requirement("r1", "고등학교 졸업 이상")]
    llm = FakeLLM(structured=[LLMJudgeOutput(judgments=[])])
    judge(llm, make_criteria(reqs), CAND, reqs, model="m")
    assert llm.calls == [("structured", "judge-55-c9")]
