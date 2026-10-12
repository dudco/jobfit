"""구조화 결과의 검증·후처리 — LLM이 아니라 코드가 책임지는 부분 (ADR-0011).

- 근거 인용이 전사에 실제로 있는지 확인하고 출처 위치(이미지·조각)를 채운다
  (떨어진 줄을 이어 붙인 인용은 모든 조각이 있으면 인정하고 quote_spliced로 표시)
- 공백만 다른 중복 요건을 병합한다 (겹침 분할로 같은 줄이 두 번 전사될 수 있음)
- id를 순서대로 부여하고, 이상 징후를 경고로 남긴다
"""
from __future__ import annotations

import re
from typing import Optional

from .criteria import Conditions, CriteriaSource, EvidenceRef, PostingCriteria, Position, Requirement
from .structure import LLMRequirement, StructuredPosting
from .transcribe import slice_at

MAX_REQUIREMENTS = 30
ABSENCE = re.compile(r"무관")       # "경력 무관", "전공무관" — 조건이 없음을 뜻함
PREFERENCE = re.compile(r"우대")     # "전공무관(상경계열 우대)"처럼 우대가 붙으면 요건으로 남긴다


BROKEN_ESCAPE = re.compile(r"\x00([0-9a-fA-F]{2})")          # '\u00b7'이 '\u0000' + 'b7'로 깨진 경우
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_text(text: str) -> str:
    """LLM 출력의 깨진 유니코드 이스케이프를 복구하고 남은 제어 문자를 버린다 (줄바꿈·탭은 유지)."""
    return CONTROL.sub("", BROKEN_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text))


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def find_quote(quote: str, transcript: str) -> Optional[int]:
    """공백을 무시하고 quote를 찾아, 전사 원문에서의 시작 위치를 돌려준다. 없으면 None."""
    needle = _compact(quote)
    if len(needle) < 2:
        return None
    positions = [i for i, ch in enumerate(transcript) if not ch.isspace()]
    haystack = "".join(transcript[i] for i in positions)
    found = haystack.find(needle)
    return None if found < 0 else positions[found]


FRAGMENT_SPLIT = re.compile(r"[\n|•]")   # 줄바꿈, 표 칸 경계, 글머리표


def find_fragments(quote: str, transcript: str) -> Optional[int]:
    """떨어진 줄·표 행을 이어 붙인 인용을 조각으로 나눠, 모든 조각이 전사에 있으면 가장 긴 조각의 위치를 돌려준다.

    LLM이 '자격요건 • 야간근무 가능자'처럼 표제와 떨어진 항목을 붙여 인용하는 경우가 있다 (X2 관찰).
    조각 하나라도 전사에 없으면 None — 지어낸 문구를 받아들이지 않는다.
    """
    fragments = [f for f in FRAGMENT_SPLIT.split(quote) if len(_compact(f)) >= 2]
    if len(fragments) < 2:
        return None
    found = [(len(_compact(f)), find_quote(f, transcript)) for f in fragments]
    if any(offset is None for _, offset in found):
        return None
    return max(found, key=lambda x: x[0])[1]


def dedupe(requirements: list[LLMRequirement]) -> list[LLMRequirement]:
    """같은 유형·같은 모집분야에서 공백만 다른 요건은 하나로. 하나라도 must면 must. 순서 유지."""
    merged: dict[tuple, LLMRequirement] = {}
    for r in requirements:
        key = (r.category, _compact(r.text), tuple(sorted(r.positions)))
        if key in merged:
            if r.priority == "must":
                merged[key].priority = "must"
            continue
        merged[key] = r.model_copy()
    return list(merged.values())


def means_no_condition(text: str) -> bool:
    """'경력 무관'처럼 조건이 없음을 뜻하는 문구인가. 프롬프트로도 막지만 코드로 한 번 더 거른다."""
    return bool(ABSENCE.search(text)) and not PREFERENCE.search(text)


def warnings_for(requirements: list[Requirement]) -> list[str]:
    if not requirements:
        return ["요건이 0개 — 이미지에 자격요건이 없는 공고(안내 배너 등)일 수 있음"]
    warnings = []
    if not any(r.priority == "must" for r in requirements):
        warnings.append("필수 요건이 없음 — 필수/우대 판별을 확인")
    if len(requirements) > MAX_REQUIREMENTS:
        warnings.append(f"요건이 {len(requirements)}개로 많음 — 요건 분리 과다 의심")
    missing = [r.id for r in requirements if "quote_not_found" in r.flags]
    if missing:
        warnings.append(f"근거 인용을 전사에서 찾지 못함: {', '.join(missing)}")
    unknown = [r.id for r in requirements if "unknown_position" in r.flags]
    if unknown:
        warnings.append(f"모집분야 목록에 없는 분야를 가리키는 요건: {', '.join(unknown)}")
    return warnings


def build_criteria(out: StructuredPosting, transcript: str, *, source: CriteriaSource,
                   models: dict[str, str], extracted_at: str) -> PostingCriteria:
    cleaned = [r.model_copy(update={"text": clean_text(r.text), "normalized": clean_text(r.normalized),
                                    "quote": clean_text(r.quote)}) for r in out.requirements]
    candidates = dedupe(cleaned)
    dropped = [r.text for r in candidates if means_no_condition(r.text)]
    known_positions = {p.name for p in out.positions}
    requirements: list[Requirement] = []
    for i, r in enumerate((r for r in candidates if not means_no_condition(r.text)), start=1):
        offset, flags = find_quote(r.quote, transcript), []
        if offset is None:
            offset = find_fragments(r.quote, transcript)
            flags.append("quote_spliced" if offset is not None else "quote_not_found")
        image_index, slice_index = slice_at(transcript, offset) if offset is not None else (None, None)
        if known_positions and any(p not in known_positions for p in r.positions):
            flags.append("unknown_position")
        requirements.append(Requirement(
            id=f"r{i}", text=r.text, normalized=r.normalized, priority=r.priority, category=r.category,
            positions=r.positions, min_years=r.min_years, min_education=r.min_education, sensitive=r.sensitive,
            evidence=EvidenceRef(quote=r.quote, image_index=image_index, slice_index=slice_index),
            flags=flags,
        ))
    warnings = warnings_for(requirements)
    if dropped:
        warnings.append(f"조건이 없음을 뜻하는 문구 제외: {', '.join(dropped)}")
    return PostingCriteria(
        source=source, extracted_at=extracted_at, models=models,
        title=out.title, company=out.company, job_family=out.job_family,
        positions=[Position(**p.model_dump()) for p in out.positions],
        requirements=requirements,
        conditions=Conditions(**out.conditions.model_dump()),
        suitable=bool(requirements),
        warnings=warnings,
    )
