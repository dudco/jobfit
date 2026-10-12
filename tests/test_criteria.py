import json

import pytest
from pydantic import ValidationError

from preprocessing.criteria import (
    CriteriaSource, EvidenceRef, PostingCriteria, Requirement, criteria_dir, list_criteria, load_criteria,
    save_criteria,
)


def make(posting_id="1", requirements=()):
    return PostingCriteria(
        source=CriteriaSource(site="saramin", posting_id=posting_id,
                              snapshot_fetched_at="2026-10-12T00:00:00+00:00", image_sha256=["abc"]),
        extracted_at="2026-10-12T01:00:00+00:00",
        models={"transcribe": "v", "structure": "t"},
        title="생산직 채용", job_family="식품 생산",
        requirements=list(requirements),
        suitable=bool(requirements),
    )


def req(**kw):
    base = dict(id="r1", text="고등학교 졸업 이상", normalized="고졸 이상", priority="must",
                category="education", evidence=EvidenceRef(quote="고등학교 졸업 이상"))
    return Requirement(**{**base, **kw})


def test_requirement_rejects_unknown_category_and_priority():
    with pytest.raises(ValidationError):
        req(category="java")            # 스킬 이름은 유형이 아니다 (ADR-0013)
    with pytest.raises(ValidationError):
        req(priority="nice-to-have")


def test_requirement_defaults():
    r = req()
    assert (r.positions, r.sensitive, r.flags, r.min_years) == ([], False, [], None)


def test_criteria_roundtrip_with_atomic_write(tmp_path):
    d = criteria_dir(tmp_path, "saramin", "1")
    assert load_criteria(d) is None
    path = save_criteria(d, make(requirements=[req()]))
    assert path == tmp_path / "criteria" / "saramin" / "1" / "criteria.json"
    assert load_criteria(d) == make(requirements=[req()])
    assert not list(d.glob("*.tmp"))
    assert json.loads(path.read_text(encoding="utf-8"))["requirements"][0]["evidence"]["quote"] == "고등학교 졸업 이상"


def test_list_criteria_sorted(tmp_path):
    for pid in ("2", "1"):
        save_criteria(criteria_dir(tmp_path, "saramin", pid), make(pid))
    assert [c.source.posting_id for c in list_criteria(tmp_path)] == ["1", "2"]
    assert list_criteria(tmp_path / "none") == []
