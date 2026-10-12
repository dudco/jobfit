"""검증 표시(flags)의 뜻 — CLI·API·UI가 같은 설명을 보여준다.

flags는 코드 검증이 LLM 출력에 붙이는 표시다 (ADR-0011, 0015). 사람이 무엇을 확인해야 하는지 알 수 있게 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FlagInfo:
    label: str
    explanation: str
    severity: Literal["warning", "info"]


FLAGS: dict[str, FlagInfo] = {
    # 조건 추출 (preprocessing/verify.py)
    "quote_not_found": FlagInfo(
        "근거 인용 없음",
        "LLM이 근거로 인용한 문장을 원문(공고 전사 또는 이력서)에서 찾지 못했다. 지어낸 근거일 수 있다 — "
        "판정이면 '확인 필요'로 낮췄다. 원본과 대조해 확인할 것",
        "warning"),
    "quote_spliced": FlagInfo(
        "이어 붙인 인용",
        "떨어진 줄을 이어 붙인 인용이다. 각 조각은 원문에서 확인됐다 — 내용 문제는 아님",
        "info"),
    "unknown_position": FlagInfo(
        "모집분야 불일치",
        "요건이 공고의 모집분야 목록에 없는 분야를 가리킨다. 해당 분야 지원자에게 적용되지 않을 수 있다",
        "warning"),
    # 지원자 판정 (scoring/verify.py)
    "no_evidence": FlagInfo(
        "근거 없는 판정",
        "충족·부분·미충족 판정에 이력서 인용이 없어 '확인 필요'로 낮췄다",
        "warning"),
    "not_judged": FlagInfo(
        "판정 누락",
        "LLM이 이 요건을 판정하지 않아 '확인 필요'로 두었다",
        "warning"),
}


def describe(code: str) -> FlagInfo:
    return FLAGS.get(code, FlagInfo(code, code, "warning"))
