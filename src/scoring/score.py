"""점수 집계와 설명 — 순수 함수 (ADR-0017). 판정만 있으면 LLM 없이 다시 계산할 수 있다."""
from __future__ import annotations

import math
from typing import Optional

from .result import PositionScore, RequirementJudgment, Weights


def credit(status: str, w: Weights) -> Optional[float]:
    """상태 점수. not_applicable은 None — 계산에서 제외."""
    return {"met": 1.0, "partial": w.partial, "unknown": w.unknown, "unmet": 0.0}.get(status)


def aggregate(judgments: list[RequirementJudgment], position: Optional[str],
              weights: Weights = Weights()) -> PositionScore:
    js = [x.model_copy() for x in judgments]
    for x in js:
        x.credit, x.contribution = credit(x.status, weights), 0.0
    must = [x for x in js if x.priority == "must" and x.credit is not None]
    pref = [x for x in js if x.priority == "preferred" and x.credit is not None]
    if not must and not pref:
        raise ValueError("점수를 매길 요건이 없음 (모두 해당 없음)")
    groups = [(must, weights.must_share), (pref, 1 - weights.must_share)] if must and pref else [(must or pref, 1.0)]
    unmet_must = [x.requirement_id for x in must if x.status == "unmet"]
    gate = weights.gate ** len(unmet_must)
    for group, share in groups:
        for x in group:
            x.contribution = 100 * gate * share * x.credit / len(group)
    raw = sum(x.contribution for x in js)
    return PositionScore(
        position=position, score=math.floor(raw + 0.5), raw=raw,
        must_met=sum(x.status == "met" for x in must), must_total=len(must),
        preferred_met=sum(x.status == "met" for x in pref), preferred_total=len(pref),
        unmet_must=unmet_must, unknown=[x.requirement_id for x in js if x.status == "unknown"],
        judgments=js,
    )


def _tag(x: RequirementJudgment) -> str:
    return "필수" if x.priority == "must" else "우대"


def summarize(ps: PositionScore, excluded_sensitive: list[str]) -> list[str]:
    """LLM 문장이 아니라 판정에서 만든 설명 — 점수와 어긋나지 않는다."""
    head = f"필수 {ps.must_total}개 중 {ps.must_met}개 충족"
    if ps.preferred_total:
        head += f" · 우대 {ps.preferred_total}개 중 {ps.preferred_met}개 충족"
    lines = [head]

    def pick(status: str) -> list[RequirementJudgment]:
        return [x for x in ps.judgments if x.status == status]

    if unmet := pick("unmet"):
        lines.append("미충족: " + "; ".join(
            f"[{_tag(x)}] {x.text}" + (f' (이력서: "{x.quotes[0]}")' if x.quotes else "") for x in unmet))
    if partial := pick("partial"):
        lines.append("부분 충족: " + "; ".join(f"[{_tag(x)}] {x.text}" for x in partial))
    if unknown := pick("unknown"):
        lines.append("확인 필요: " + ", ".join(x.text for x in unknown))
    if excluded_sensitive:
        lines.append(f"법정 우대 {len(excluded_sensitive)}개는 점수에 반영하지 않음")
    return lines
