from openai.lib._pydantic import to_strict_json_schema  # OpenAI strict 스키마 호환성 확인용

from preprocessing.structure import StructuredPosting, structure

from .fakes import FakeLLM

EMPTY = StructuredPosting.model_validate({
    "title": "t", "company": None, "job_family": "f", "positions": [], "requirements": [],
    "conditions": {"employment_type": None, "locations": [], "schedule": None, "others": []},
})


def test_structure_sends_whole_transcript_once():
    seen = {}

    def respond(user):
        seen["user"] = user
        return EMPTY

    llm = FakeLLM(structured=[respond])
    assert structure(llm, "## 지원자격\n- 고졸 이상", model="t", posting_id="55") == EMPTY
    assert "## 지원자격\n- 고졸 이상" in seen["user"]
    assert llm.calls == [("structured", "structure-55")]


def test_llm_output_schema_is_openai_strict_compatible():
    schema = to_strict_json_schema(StructuredPosting)
    assert schema["additionalProperties"] is False
