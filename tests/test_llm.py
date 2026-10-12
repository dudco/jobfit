from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from llm import CachedLLM, OpenAILLM, image_data_url

from .fakes import FakeLLM


class Completions:
    """openai client.chat.completions 대역."""

    def __init__(self, parsed=None):
        self.parsed = parsed
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="전사 결과"))])

    def parse(self, **kwargs):
        self.kwargs = kwargs
        msg = SimpleNamespace(parsed=self.parsed, refusal="정책상 거부")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def client(comp):
    return SimpleNamespace(chat=SimpleNamespace(completions=comp))


class Out(BaseModel):
    v: int


def png(tmp_path, name="a.png", data=b"img-bytes"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_image_data_url_uses_mime_by_extension(tmp_path):
    assert image_data_url(png(tmp_path, "a.png")).startswith("data:image/png;base64,")
    assert image_data_url(png(tmp_path, "b.jpg")).startswith("data:image/jpeg;base64,")


def test_vision_text_sends_context_then_high_detail_image(tmp_path):
    comp = Completions()
    out = OpenAILLM(client(comp)).vision_text(model="m", system="sys", image=png(tmp_path), user_text="직전 줄")
    assert out == "전사 결과"
    system, user = comp.kwargs["messages"]
    assert system == {"role": "system", "content": "sys"}
    assert user["content"][0] == {"type": "text", "text": "직전 줄"}
    assert user["content"][1]["type"] == "image_url"
    assert user["content"][1]["image_url"]["detail"] == "high"


def test_structured_returns_parsed_or_raises_with_refusal():
    assert OpenAILLM(client(Completions(parsed=Out(v=1)))).structured(
        model="m", system="s", user="u", schema=Out) == Out(v=1)
    with pytest.raises(RuntimeError, match="정책상 거부"):
        OpenAILLM(client(Completions(parsed=None))).structured(model="m", system="s", user="u", schema=Out)


def test_cache_hit_skips_inner_llm_and_needs_no_client(tmp_path):
    inner = FakeLLM(vision=["첫 응답"], structured=[Out(v=7)])
    cached = CachedLLM(lambda: inner, tmp_path / "cache")
    img = png(tmp_path)
    assert cached.vision_text(model="m", system="s", image=img, tag="transcribe-1-00") == "첫 응답"
    assert cached.structured(model="m", system="s", user="u", schema=Out, tag="structure-1") == Out(v=7)

    def no_client():
        raise AssertionError("캐시 적중이면 내부 LLM을 만들지 않아야 한다 (API 키 불필요)")

    again = CachedLLM(no_client, tmp_path / "cache")
    assert again.vision_text(model="m", system="s", image=img, tag="transcribe-1-00") == "첫 응답"
    result = again.structured(model="m", system="s", user="u", schema=Out, tag="structure-1")
    assert result == Out(v=7) and isinstance(result, Out)
    assert len(list((tmp_path / "cache").glob("transcribe-1-00-*.json"))) == 1


def test_cache_key_changes_with_image_bytes_and_model(tmp_path):
    inner = FakeLLM(vision=["a", "b", "c"])
    cached = CachedLLM(lambda: inner, tmp_path / "cache")
    cached.vision_text(model="m", system="s", image=png(tmp_path, "x.png", b"1"))
    cached.vision_text(model="m", system="s", image=png(tmp_path, "y.png", b"2"))  # 이미지 바이트가 다름
    cached.vision_text(model="m2", system="s", image=png(tmp_path, "x.png", b"1"))  # 모델이 다름
    assert [kind for kind, _ in inner.calls] == ["vision", "vision", "vision"]


def test_empty_string_response_is_cached(tmp_path):
    inner = FakeLLM(vision=[""])
    cached = CachedLLM(lambda: inner, tmp_path / "cache")
    img = png(tmp_path)
    assert cached.vision_text(model="m", system="s", image=img) == ""
    assert cached.vision_text(model="m", system="s", image=img) == ""
    assert len(inner.calls) == 1
