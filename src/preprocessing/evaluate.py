"""추출 결과를 사람이 만든 정답 요건 목록과 비교한다 (스펙 02 실험 X1–X3).

평가 전용이다 — 파이프라인은 정답을 읽지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .criteria import Category, PostingCriteria, Priority, Requirement

MATCH_THRESHOLD = 0.6
MIN_CONTAINMENT = 0.5   # 짧은 쪽이 긴 쪽 길이의 이 비율 이상일 때만 '포함'을 일치로 본다


class TruthItem(BaseModel):
    text: str
    priority: Priority
    category: Category
    positions: list[str] = Field(default_factory=list)
    sensitive: bool = False
    aliases: list[str] = Field(default_factory=list)


class Truth(BaseModel):
    posting_id: str
    requirements: list[TruthItem]


def load_truth(path: Path) -> Truth:
    return Truth.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text).lower()


def similarity(a: str, b: str) -> float:
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return 0.0
    short, long = sorted((ka, kb), key=len)
    if short in long and len(short) / len(long) >= MIN_CONTAINMENT:
        return 1.0
    return SequenceMatcher(None, ka, kb).ratio()


def _ratio(n: int, d: int) -> float:
    return n / d if d else 1.0


@dataclass
class Evaluation:
    matched: list[tuple[TruthItem, Requirement]]
    missed: list[TruthItem]
    extra: list[Requirement]

    @property
    def recall(self) -> float:
        return _ratio(len(self.matched), len(self.matched) + len(self.missed))

    @property
    def precision(self) -> float:
        return _ratio(len(self.matched), len(self.matched) + len(self.extra))

    @property
    def must_recall(self) -> float:
        must_matched = sum(t.priority == "must" for t, _ in self.matched)
        must_total = must_matched + sum(t.priority == "must" for t in self.missed)
        return _ratio(must_matched, must_total)

    @property
    def priority_agreement(self) -> float:
        return _ratio(sum(t.priority == r.priority for t, r in self.matched), len(self.matched))

    @property
    def category_agreement(self) -> float:
        return _ratio(sum(t.category == r.category for t, r in self.matched), len(self.matched))


def evaluate(truth: Truth, criteria: PostingCriteria, *, threshold: float = MATCH_THRESHOLD) -> Evaluation:
    """정답 항목마다 가장 비슷한 추출 요건 하나를 짝짓는다 (탐욕적, 1:1)."""
    remaining = list(criteria.requirements)
    matched: list[tuple[TruthItem, Requirement]] = []
    missed: list[TruthItem] = []
    for item in truth.requirements:
        names = [item.text, *item.aliases]
        best, best_score = None, 0.0
        for r in remaining:
            score = max(similarity(n, t) for n in names for t in (r.text, r.normalized, r.evidence.quote))
            if score > best_score:
                best, best_score = r, score
        if best is not None and best_score >= threshold:
            matched.append((item, best))
            remaining.remove(best)
        else:
            missed.append(item)
    return Evaluation(matched=matched, missed=missed, extra=remaining)
