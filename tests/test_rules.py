import pytest

from scoring.candidate import Candidate
from scoring.rules import education_status, experience_years, years_status


def cand(education=(), experiences=()):
    return Candidate(id="c", name="n", education=list(education), experiences=list(experiences))


def edu(level, status="graduated"):
    return {"level": level, "school": "s", "status": status}


def job(start, end):
    return {"company": "c", "role": "r", "start": start, "end": end}


@pytest.mark.parametrize("education, minimum, expected", [
    ([edu("master")], "bachelor", None),                    # 상위 학력은 충족 → LLM 판정 유지
    ([edu("associate")], "high_school", None),
    ([edu("bachelor", "expected")], "bachelor", None),      # 졸업 예정도 수준은 인정 (기한은 LLM)
    ([edu("high_school")], "bachelor", "unmet"),
    ([edu("high_school"), edu("bachelor", "dropped")], "bachelor", "unmet"),   # 중퇴는 세지 않음
    ([edu("bachelor", "enrolled")], "bachelor", "unmet"),
    ([], "high_school", "unknown"),                         # 학력 정보 없음 ≠ 미달
])
def test_education_status(education, minimum, expected):
    status, reason = education_status(cand(education=education), minimum)
    assert status == expected and "요구" in reason


def test_experience_years_merges_overlaps_and_ongoing():
    c = cand(experiences=[job("2020-01", "2020-12"), job("2020-07", "2021-06"), job("2023-01", None)])
    assert experience_years(c, [1, 2], today="2026-10") == pytest.approx(1.5)          # 2020-01~2021-06
    assert experience_years(c, [3], today="2026-10") == pytest.approx(3 + 10 / 12)     # 2023-01~2026-10
    assert experience_years(c, [1, 99, 0], today="2026-10") == pytest.approx(1.0)      # 없는 번호는 무시


@pytest.mark.parametrize("have, need, expected", [(3, 3, "met"), (1.8, 3, "partial"), (1.7, 3, "unmet"), (0, 0, "met")])
def test_years_status(have, need, expected):
    assert years_status(have, need) == expected
