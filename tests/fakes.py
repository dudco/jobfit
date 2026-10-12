"""LLM 프로토콜 대역. 실제 API를 호출하지 않는다."""
from __future__ import annotations


class FakeLLM:
    """vision: 응답 문자열 목록(순서대로 소비)
    structured: 응답 목록 — pydantic 객체, 또는 user 프롬프트를 받아 객체를 돌려주는 함수
    calls: [(종류, 태그)] — 호출 기록
    """

    def __init__(self, vision=None, structured=None):
        self.vision = list(vision or [])
        self.structured_responses = list(structured or [])
        self.calls: list[tuple[str, str]] = []
        self.vision_inputs: list[dict] = []

    def vision_text(self, *, model, system, image, user_text=None, tag=""):
        self.calls.append(("vision", tag))
        self.vision_inputs.append({"image": image, "user_text": user_text})
        return self.vision.pop(0)

    def structured(self, *, model, system, user, schema, tag=""):
        self.calls.append(("structured", tag))
        resp = self.structured_responses.pop(0)
        return resp(user) if callable(resp) else resp
