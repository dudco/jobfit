import json

import pytest

from scoring.candidate import Candidate, load_candidates, render

BASE = {
    "id": "c1", "name": "김하늘", "headline": "경영학 전공 신입", "address": "서울 강서구",
    "desired_positions": ["재무"],
    "education": [{"level": "bachelor", "school": "한국대학교", "major": "경영학과",
                   "status": "graduated", "graduation": "2026-02"}],
    "experiences": [{"company": "가나상사", "role": "회계 인턴", "start": "2025-07", "end": "2025-12",
                     "description": "월 결산 보조"}],
    "certifications": [{"name": "전산회계 1급", "acquired": "2024-11"}],
    "languages": [{"language": "영어", "test": "TOEIC", "score": "915", "acquired": "2025-08"}],
    "military": "군필",
    "declarations": ["2027년 1월 입사 가능"],
    "skills": ["엑셀"],
    "self_intro": "첫 문단\n\n둘째 문단",
    "source": {"method": "mock", "format": None, "file_sha256": None, "extracted_text": None},
    "meta": {"target_posting": "55189170", "label": "perfect", "intent": "같은 단어로 충족",
             "expected": [{"requirement": "공인영어성적", "status": "met"}]},
}


def test_render_numbers_one_fact_per_line():
    lines = render(Candidate.model_validate(BASE)).splitlines()
    assert lines[0] == "L01 [기본] 김하늘 — 경영학 전공 신입"
    assert "L04 [학력] 학사 · 한국대학교 · 경영학과 · 졸업 (2026-02)" in lines
    assert any(l.endswith("[경력 1] 가나상사 · 회계 인턴 · 2025-07~2025-12") for l in lines)
    assert any(l.endswith("[경력 1 내용] 월 결산 보조") for l in lines)
    assert any(l.endswith("[자기 신고] 2027년 1월 입사 가능") for l in lines)
    assert [l.split(" ", 1)[1] for l in lines if "[자기소개]" in l] == ["[자기소개] 첫 문단", "[자기소개] 둘째 문단"]


def test_render_never_includes_meta_or_source():
    text = render(Candidate.model_validate(BASE))
    for secret in ("perfect", "55189170", "같은 단어로 충족", "expected", "mock"):
        assert secret not in text


def test_source_defaults_to_mock():
    data = {k: v for k, v in BASE.items() if k != "source"}
    assert Candidate.model_validate(data).source.method == "mock"


def test_ongoing_job_and_optional_fields():
    c = Candidate.model_validate({**BASE, "address": None, "military": None,
                                  "experiences": [{"company": "A", "role": "B", "start": "2020-01", "end": None}]})
    text = render(c)
    assert "2020-01~재직 중" in text and "[주소]" not in text and "[병역]" not in text


def test_load_candidates_sorted_and_reports_bad_file(tmp_path):
    (tmp_path / "b.json").write_text(json.dumps({**BASE, "id": "b"}), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps({**BASE, "id": "a"}), encoding="utf-8")
    assert [c.id for c in load_candidates(tmp_path)] == ["a", "b"]
    (tmp_path / "z.json").write_text('{"id": "z"}', encoding="utf-8")
    with pytest.raises(ValueError, match="z.json"):
        load_candidates(tmp_path)


def test_duplicate_ids_rejected(tmp_path):
    for f in ("a.json", "b.json"):
        (tmp_path / f).write_text(json.dumps(BASE), encoding="utf-8")
    with pytest.raises(ValueError, match="중복"):
        load_candidates(tmp_path)
