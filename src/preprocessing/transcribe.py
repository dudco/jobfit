"""조각 이미지 → 원문 전사 (ADR-0010, ADR-0011).

조각 경계를 주석으로 남겨, 구조화 결과의 근거를 원본 이미지 위치까지 거슬러 올라갈 수 있게 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from llm import LLM

from .prompts import TRANSCRIBE_SYSTEM

MARK = "<!-- slice {index:02d} image={image} part={part} -->"
MARK_RE = re.compile(r"<!-- slice (\d+) image=(\d+) part=(\d+) -->")
TAIL_LINES = 3


@dataclass(frozen=True)
class SliceRef:
    path: Path
    image_index: int   # 스냅샷 이미지 번호
    part: int          # 그 이미지 안에서 몇 번째 조각


def transcribe(llm: LLM, slices: list[SliceRef], *, model: str, posting_id: str) -> str:
    parts: list[str] = []
    tail = ""
    for i, ref in enumerate(slices):
        user_text = f"직전 조각의 마지막 줄:\n{tail}" if tail else None
        text = llm.vision_text(model=model, system=TRANSCRIBE_SYSTEM, image=ref.path,
                               user_text=user_text, tag=f"transcribe-{posting_id}-{i:02d}").strip()
        parts.append(MARK.format(index=i, image=ref.image_index, part=ref.part) + "\n" + text)
        tail = "\n".join(text.splitlines()[-TAIL_LINES:])
    return "\n\n".join(parts)


def slice_at(transcript: str, offset: int) -> tuple[Optional[int], Optional[int]]:
    """offset 위치를 포함하는 조각의 (이미지 번호, 조각 번호)."""
    found: tuple[Optional[int], Optional[int]] = (None, None)
    for m in MARK_RE.finditer(transcript):
        if m.start() > offset:
            break
        found = (int(m.group(2)), int(m.group(1)))
    return found
