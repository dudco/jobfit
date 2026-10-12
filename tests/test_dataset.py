"""목업 데이터셋(제출물)의 구성 규칙 — 공고당 완벽 2·부분 3·미스매치 1, 의도 기록, 민감 정보 없음."""
from collections import Counter

from scoring.candidate import load_candidates
from settings import ROOT

DATASET = ROOT / "dataset" / "candidates"


def test_twelve_candidates_two_postings_with_2_3_1_split():
    cands = load_candidates(DATASET)
    assert len(cands) == 12
    by_posting = Counter((c.meta.target_posting, c.meta.label) for c in cands)
    for posting in ("55189170", "55162188"):
        assert (by_posting[(posting, "perfect")], by_posting[(posting, "partial")],
                by_posting[(posting, "mismatch")]) == (2, 3, 1)


def test_every_candidate_documents_intent_and_expected_judgments():
    for c in load_candidates(DATASET):
        assert c.meta.intent and c.meta.expected, c.id
        assert c.id.split("-")[1] == c.meta.label, c.id
        assert c.source.method == "mock", c.id


def test_no_sensitive_personal_fields():
    for path in DATASET.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        for word in ("장애", "보훈", "생년", "나이", "성별"):
            assert word not in text, (path.name, word)
