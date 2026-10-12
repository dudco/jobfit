"""직무 요건이 없는 공고에서 '모집분야 적합도' 우대 요건을 도출한다 (ADR-0022).

공고 이미지에 공통 자격(해외여행 결격, 병역 등)만 있고 직무 요건이 없으면 모든 지원자가 비슷한 점수가 된다.
그때만, 이미지에서 읽은 모집분야 이름(과 직무)마다 "그 분야 관련 경력·전공·자격" 우대 요건을 만든다.
공고에 명시된 요건이 아니므로 `derived_from_position` 표시를 붙이고, 가중치(`use_derived`)로 끌 수 있다.
"""
from __future__ import annotations

from preprocessing.criteria import EvidenceRef, PostingCriteria, Requirement

JOB_CATEGORIES = {"experience", "skill", "domain_knowledge", "certification"}
DERIVED_FLAG = "derived_from_position"


def needs_position_fit(criteria: PostingCriteria) -> bool:
    """모집분야가 있고, 직무와 관련된 요건(직무 유형이거나 일부 분야에만 걸린 요건)이 하나도 없을 때."""
    names = {p.name for p in criteria.positions}
    if not names:
        return False
    for r in criteria.requirements:
        if r.sensitive:
            continue
        if r.category in JOB_CATEGORIES or (r.positions and set(r.positions) < names):
            return False
    return True


def position_fit_requirements(criteria: PostingCriteria) -> list[Requirement]:
    out = []
    for i, p in enumerate(criteria.positions, start=1):
        label = f"'{p.name}'" + (f"({p.duties})" if p.duties else "")
        out.append(Requirement(
            id=f"p{i}", text=f"{label} 직무 관련 경력·전공·자격", normalized=f"{p.name} 직무 적합",
            priority="preferred", category="experience", positions=[p.name],
            min_years=None, min_education=None, sensitive=False,
            evidence=EvidenceRef(quote=p.name, image_index=None, slice_index=None), flags=[DERIVED_FLAG],
        ))
    return out
