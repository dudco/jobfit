import pytest

from jobfit.crawler.saramin import parse_rec_idx


@pytest.mark.parametrize("ref", [
    "51234567",
    " 51234567 ",
    "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=list&rec_idx=51234567",
    "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=51234567&location=ts",
])
def test_parse_rec_idx(ref):
    assert parse_rec_idx(ref) == "51234567"


@pytest.mark.parametrize("ref", ["", "abc", "https://www.saramin.co.kr/zf_user/search?searchword=회계"])
def test_parse_rec_idx_rejects_refs_without_id(ref):
    with pytest.raises(ValueError):
        parse_rec_idx(ref)
