"""스코어링 테스트용 공고 조건 픽스처."""
from preprocessing.criteria import (Conditions, CriteriaSource, EvidenceRef, PostingCriteria, Position,
                                    Requirement)


def make_requirement(rid, text, priority="must", category="other", positions=(), sensitive=False,
                     min_education=None, min_years=None):
    return Requirement(id=rid, text=text, normalized=text, priority=priority, category=category,
                       positions=list(positions), min_years=min_years, min_education=min_education,
                       sensitive=sensitive, evidence=EvidenceRef(quote=text, image_index=0, slice_index=0))


def make_criteria(requirements, positions=(), posting_id="55", suitable=True):
    return PostingCriteria(
        source=CriteriaSource(site="saramin", posting_id=posting_id, snapshot_fetched_at="t0", image_sha256=["x"]),
        extracted_at="t1", models={"transcribe": "v", "structure": "t"}, title="테스트 공고", company="OO",
        job_family="테스트 직군",
        positions=[Position(name=p, group=None, duties=None, location=None) for p in positions],
        requirements=list(requirements),
        conditions=Conditions(employment_type=None, locations=[], schedule=None, others=[]),
        suitable=suitable, warnings=[],
    )
